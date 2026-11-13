"""O motor como serviço (ADR-0022): a API dos aparelhos rodando junto do agente.

``shiro serve`` sobe o agente e a API. O programa do PC entra com a chave do
aparelho "Este PC", criada na primeira execução e guardada na pasta de dados do
usuário, com a mesma proteção do banco.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import socket
import sys
from pathlib import Path

from fastapi import FastAPI

from shiro.application.devices.confirmations import RemoteConfirmations
from shiro.application.devices.service import DeviceRegistry
from shiro.bootstrap.app import App
from shiro.domain.devices.models import Device
from shiro.domain.models import AgentResult
from shiro.interfaces.api.devices import create_device_api
from shiro.interfaces.api.server import _server_class  # pyright: ignore[reportPrivateUsage]
from shiro.interfaces.voice.session import VoiceSession

log = logging.getLogger(__name__)

LOCAL_DEVICE = "Este PC"
LOCAL_TOKEN_FILE = "local-client.token"  # noqa: S105 - nome de arquivo, não a chave


async def ensure_local_token(registry: DeviceRegistry, folder: Path) -> str:
    """A chave do programa deste PC: reaproveita a do arquivo se ainda vale, senão cria outra."""
    file = folder / LOCAL_TOKEN_FILE
    saved = _read(file)
    if saved and await registry.authenticate(saved) is not None:
        return saved
    paired = await registry.complete_pairing(registry.start_pairing().code, LOCAL_DEVICE)
    if paired is None:  # pragma: no cover - o código acabou de ser criado
        msg = "não consegui criar a chave do programa deste PC"
        raise RuntimeError(msg)
    _write(file, paired.token)
    return paired.token


ENGINE_FILE = "engine.json"
_RUN = "from shiro.interfaces.cli.main import main; raise SystemExit(main(['serve']))"


def write_launch_spec(folder: Path) -> None:
    """Grava como ligar o motor de novo, para o programa do PC fazer isso sozinho.

    Prefere o ``pythonw.exe`` (sem janela de terminal) do mesmo ambiente.
    """
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    spec = {"exe": str(windowless if windowless.exists() else python), "args": ["-c", _RUN]}
    _write(folder / ENGINE_FILE, json.dumps(spec))


def _read(file: Path) -> str:
    return file.read_text("utf-8").strip() if file.exists() else ""


def _write(file: Path, token: str) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(token, "utf-8")


class _Quiet(io.StringIO):
    """Descarta o que a sessão de voz imprimiria: o motor não tem terminal."""

    def write(self, text: str) -> int:
        return len(text)


class VoiceBox:
    """Ouvido e voz do motor: montados no primeiro uso (carregar o Whisper leva alguns segundos)."""

    def __init__(self, app: App, turn: asyncio.Lock) -> None:
        self._app = app
        self._turn = turn
        self._session: VoiceSession | None = None
        self._busy = asyncio.Lock()

    async def _ready(self) -> VoiceSession:
        if self._session is None:
            from shiro.domain.voice.audio import Cues
            from shiro.infrastructure.voice.devices import SoundDeviceMicrophone, SoundDevicePlayer
            from shiro.infrastructure.voice.silero import SileroVAD
            from shiro.interfaces.voice.runtime import (
                endpoint_for,
                tts_for,
                whisper_for,
                with_commands,
            )

            settings = self._app.settings
            voice = settings.voice
            tts, _ = tts_for(settings)
            stt = with_commands(await whisper_for(settings), settings, self._app.router)
            await stt.load()
            self._session = VoiceSession(
                run_turn=self._app.agent.run_turn,
                stt=stt,
                tts=tts,
                player=SoundDevicePlayer(voice.output_device),
                microphone=SoundDeviceMicrophone(voice.input_device, voice.capture),
                detector=SileroVAD(),
                listen=endpoint_for(settings),
                cues=Cues.generate(voice.cue_volume),
                name=settings.general.assistant_name,
                volume=voice.tts.volume,
                out=_Quiet(),
            )
        return self._session

    async def exchange(self, device: Device) -> tuple[str, AgentResult] | None:
        """Bipe, escuta, responde em voz alta. ``None`` se ninguém falou."""
        async with self._busy:
            session = await self._ready()
            heard = await session.listen()
            if heard is None:
                return None
            async with self._turn:
                log.info("pedido por voz de %s", device.name)
                result = await self._app.agent.run_turn(heard)
            await session.say(result.text)
            return heard, result


def engine_api(
    app: App,
    registry: DeviceRegistry,
    confirmations: RemoteConfirmations,
    *,
    local_device_id: str = "",
) -> FastAPI:
    turn = asyncio.Lock()  # o agente atende um pedido por vez
    voice = VoiceBox(app, turn)

    async def chat(text: str, device: Device) -> AgentResult:
        async with turn:
            log.info("pedido de %s", device.name)
            return await app.agent.run_turn(text)

    def lessons() -> list[dict[str, str]]:
        return [{"trigger": x.trigger, "meaning": x.meaning} for x in app.lessons.lessons()]

    def can_pair(device: Device) -> bool:
        return bool(local_device_id) and device.id == local_device_id

    return create_device_api(
        registry=registry,
        chat=chat,
        confirmations=confirmations,
        lessons=lessons,
        voice=voice.exchange,
        can_pair=can_pair,
        address=(app.settings.devices.host, app.settings.devices.port),
    )


class EngineServer:
    """Uvicorn com a API dos aparelhos, no mesmo laço do asyncio que o agente."""

    def __init__(self, api: FastAPI, *, host: str, port: int) -> None:
        import uvicorn

        config = uvicorn.Config(
            api, host=host, port=port, log_config=None, access_log=False, lifespan="off"
        )
        self._server = _server_class()(config)
        self._task: asyncio.Task[None] | None = None
        self.host, self.port = host, port

    async def start(self) -> None:
        sock = socket.socket(
            socket.AF_INET6 if ":" in self.host else socket.AF_INET, socket.SOCK_STREAM
        )
        try:
            if sys.platform == "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # pyright: ignore[reportAttributeAccessIssue]
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(16)
        except OSError:
            sock.close()
            raise
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
        for _ in range(100):
            if self._server.started or self._task.done():
                break
            await asyncio.sleep(0.05)
        if self._task.done():
            self._task.result()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(self._task, 5)
        self._task = None
