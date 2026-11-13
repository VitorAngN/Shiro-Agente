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
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from shiro.application.bus import EventBus
from shiro.application.devices.confirmations import Pending, RemoteConfirmations
from shiro.application.devices.service import DeviceRegistry
from shiro.application.voice.dictation import is_stop, spoken_punctuation
from shiro.bootstrap.app import App
from shiro.domain.devices.models import Device
from shiro.domain.events import BackgroundNotice, TurnFinished, TurnProgress, TurnStarted
from shiro.domain.models import AgentResult, DecisionKind
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


_DICTATION_SILENCES = 3  # tantas escutas seguidas sem fala encerram o ditado


class Activity:
    """O que a SHIRO está fazendo agora: o programa mostra isto numa barra de progresso."""

    IDLE = "idle"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.stage = self.IDLE
        self.detail = ""
        self._since = clock()
        self._turn_since: float | None = None

    def set(self, stage: str, detail: str) -> None:
        if stage != self.IDLE and self._turn_since is None:
            self._turn_since = self._clock()
        if stage == self.IDLE:
            self._turn_since = None
        self.stage, self.detail, self._since = stage, detail, self._clock()

    def idle(self) -> None:
        self.set(self.IDLE, "")

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        return {
            "stage": self.stage,
            "detail": self.detail,
            "seconds": round(now - self._since, 1),
            "total_seconds": round(now - self._turn_since, 1) if self._turn_since else 0.0,
        }

    def follow(self, bus: EventBus) -> None:
        """Acompanha os turnos do agente pelo barramento de eventos."""

        async def started(event: TurnStarted) -> None:
            self.set("thinking", "entendendo o pedido")

        async def progress(event: TurnProgress) -> None:
            self.set(event.stage, event.detail)

        async def finished(event: TurnFinished) -> None:
            if self.stage != "speaking":
                self.idle()

        bus.subscribe(TurnStarted, started)
        bus.subscribe(TurnProgress, progress)
        bus.subscribe(TurnFinished, finished)


class VoiceBox:
    """Ouvido e voz do motor: montados no primeiro uso (carregar o Whisper leva alguns segundos).

    Com a escuta do nome ligada, o microfone fica aberto e "Shiro, ..." já vira pedido,
    sem clicar em nada (ADR-0016). Cada conversa por voz entra em ``history``, que o
    programa busca para mostrar na tela.
    """

    def __init__(
        self, app: App, turn: asyncio.Lock, confirmations: RemoteConfirmations | None = None
    ) -> None:
        self._app = app
        self._turn = turn
        self._confirmations = confirmations
        self.activity = Activity()
        self._voice_turn = False
        self._asking: set[asyncio.Task[None]] = set()
        if confirmations is not None:
            confirmations.listener = self._confirm_aloud
        self._session: VoiceSession | None = None
        self._busy = asyncio.Lock()
        self._wake: Any = None
        self._wake_task: asyncio.Task[None] | None = None
        self.history: list[dict[str, Any]] = []
        self.problem = ""

    @property
    def listening_for_name(self) -> bool:
        return self._wake_task is not None and not self._wake_task.done() and self._wake.enabled

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
            tts, line = tts_for(settings)
            log.info(line)
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
            self.activity.set("listening", "preparando o microfone")
            try:
                session = await self._ready()
                self.activity.set("listening", "ouvindo você")
                heard = await self._listen(session)
                if heard is None:
                    return None
                return heard, await self._answer(session, heard, device.name, source="botão")
            finally:
                self.activity.idle()

    async def _listen(self, session: VoiceSession, *, quiet: bool = False) -> str | None:
        """Escuta com prazo de relógio: se o microfone parar de mandar som, não fica preso."""
        settings = getattr(self._app, "settings", None)
        listen = settings.voice.listen if settings is not None else None
        limit = (listen.start_timeout_s + listen.max_utterance_s + 10) if listen else 40.0
        for attempt in range(2):  # fluxo travado: reabre o microfone uma vez e tenta de novo
            try:
                listening = session.listen(quiet=True) if quiet else session.listen()
                heard = await asyncio.wait_for(listening, limit)
            except (TimeoutError, OSError, RuntimeError) as exc:
                log.warning("voz: o microfone travou (%s); reabrindo", exc or "sem resposta")
                if attempt == 0:
                    continue
                self.problem = "o microfone parou de responder; tente de novo"
                return None
            self.problem = ""
            return heard
        return None

    async def _answer(
        self, session: VoiceSession, heard: str, who: str, *, source: str
    ) -> AgentResult:
        async with self._turn:
            log.info("pedido por voz de %s", who)
            self._voice_turn = True
            started = time.monotonic()
            try:
                result = await self._app.agent.run_turn(heard)
            finally:
                self._voice_turn = False
            log.info(
                "voz: turno %s em %.1f s (%s)",
                result.tier.value,
                time.monotonic() - started,
                ", ".join(c.call.name for c in result.calls) or "sem ação",
            )
        self.history.append(
            {
                "id": len(self.history) + 1,
                "source": source,
                "heard": heard,
                "text": result.text,
                "tier": result.tier.value,
                "latency_ms": result.latency_ms,
                "tools": [executed.call.name for executed in result.calls],
            }
        )
        del self.history[:-50]
        self.activity.set("speaking", "respondendo")
        await session.say(result.text)
        await self._dictate(session)
        self.activity.idle()
        return result

    async def _dictate(self, session: VoiceSession) -> None:
        """Modo ditado (ADR-0026): escreve cada frase falada até ouvir "parar ditado"."""
        dictation = getattr(self._app, "dictation", None)
        if dictation is None or not dictation.requested:
            return
        dictation.requested = False
        silences = 0
        while silences < _DICTATION_SILENCES:
            self.activity.set("listening", 'ditado: fale o texto ("parar ditado" encerra)')
            heard = await self._listen(session, quiet=True)
            if heard is None:
                silences += 1
                continue
            silences = 0
            if is_stop(heard):
                break
            written = spoken_punctuation(heard)
            self.activity.set("tool", "ditado: escrevendo")
            await dictation.write(written if written.endswith(("\n", "\t")) else written + " ")
            self.history.append(
                {
                    "id": len(self.history) + 1,
                    "source": "nome",
                    "heard": heard,
                    "text": "(escrito)",
                    "tier": "T0",
                    "latency_ms": 0,
                    "tools": ["dictation"],
                }
            )
            del self.history[:-50]
        self.activity.set("speaking", "respondendo")
        await session.say("Ditado encerrado.")

    async def on_notice(self, event: BackgroundNotice) -> None:
        """Uma espera ou um vigia agiu: aparece na conversa e é dito em voz alta."""
        self.history.append(
            {
                "id": len(self.history) + 1,
                "source": "nome",
                "heard": "(em segundo plano)",
                "text": event.text,
                "tier": "T0",
                "latency_ms": 0,
                "tools": ["wait"],
            }
        )
        del self.history[:-50]
        if self._session is not None and not self._busy.locked():
            async with self._busy:
                await self._session.say(event.text)

    # ------------------------------------------------------------ confirmação por voz

    def _confirm_aloud(self, pending: Pending) -> None:
        """Pedido feito por voz: a pergunta também é feita em voz alta ("sim" ou "não").

        O botão na tela continua valendo; o que responder primeiro decide. Ação
        crítica (R3) só no botão, porque a voz pode vir de um vídeo.
        """
        if not self._voice_turn or self._session is None:
            return
        if pending.kind is DecisionKind.CONFIRM_PHYSICAL:
            return
        task = asyncio.get_running_loop().create_task(self._ask_aloud(self._session, pending))
        self._asking.add(task)
        task.add_done_callback(self._asking.discard)

    async def _ask_aloud(self, session: VoiceSession, pending: Pending) -> None:
        from shiro.domain.voice.speech import yes_or_no

        confirmations = self._confirmations
        if confirmations is None:
            return
        question = f"{pending.prompt} Sim ou não?"
        for _ in range(2):
            if not confirmations.is_waiting(pending.id):
                return
            await session.say(question)
            if not confirmations.is_waiting(pending.id):
                return
            heard = await session.listen()
            if heard is None or not confirmations.is_waiting(pending.id):
                return
            answer = yes_or_no(heard)
            if answer is not None:
                confirmations.answer(pending.id, answer)
                return
            question = "Não entendi. Sim ou não?"

    # ------------------------------------------------------------ escuta do nome

    def wake(self) -> None:
        """Ouviu só o nome ("Shiro"): bipe e escuta o pedido."""
        asyncio.get_running_loop().create_task(self._after_name(None))

    def command(self, text: str) -> None:
        """Ouviu o nome junto do pedido ("Shiro, abre a Steam")."""
        asyncio.get_running_loop().create_task(self._after_name(text))

    async def _after_name(self, text: str | None) -> None:
        if self._busy.locked():
            return
        async with self._busy:
            try:
                session = await self._ready()
                if not text:
                    self.activity.set("listening", "ouvindo o pedido")
                started = time.monotonic()
                heard = text or await self._listen(session)
                if heard:
                    log.info(
                        "voz: pedido pronto em %.1f s depois do nome", time.monotonic() - started
                    )
                    await self._answer(session, heard, "voz", source="nome")
            finally:
                self.activity.idle()

    async def set_listening(self, enabled: bool) -> None:
        if not enabled:
            if self._wake is not None:
                self._wake.enabled = False
            return
        if self._wake_task is not None and not self._wake_task.done():
            self._wake.enabled = True
            return
        from shiro.infrastructure.voice.devices import SoundDeviceMicrophone
        from shiro.infrastructure.voice.silero import SileroVAD
        from shiro.infrastructure.voice.wake import WakeListener
        from shiro.interfaces.voice.runtime import endpoint_for, whisper_for

        session = await self._ready()
        settings = self._app.settings
        voice, word = settings.voice, settings.voice.wake_word
        check = await whisper_for(settings, word.check_model, threads=2)
        await check.load()
        self._wake = WakeListener(
            microphone=SoundDeviceMicrophone(voice.input_device, voice.capture),
            events=self,
            is_idle=lambda: not self._busy.locked(),
        )

        async def run() -> None:
            failures = 0
            while True:
                try:
                    await self._wake.run_whisper(
                        vad=SileroVAD(),
                        check=check,
                        full=session._stt,  # pyright: ignore[reportPrivateUsage]
                        phrases=word.phrases,
                        listen=endpoint_for(settings),
                        max_phrase_s=word.max_phrase_s,
                    )
                    return
                except (OSError, RuntimeError) as exc:
                    # microfone travou ou sumiu (fone desligado): reabre sozinho
                    failures += 1
                    log.warning("escuta do nome: %s; reabrindo o microfone", exc)
                    if failures >= 20:
                        self.problem = f"a escuta do nome parou: {exc}"
                        return
                    await asyncio.sleep(min(failures, 5))
                except Exception as exc:
                    log.exception("a escuta do nome caiu")
                    self.problem = f"a escuta do nome parou: {exc}"
                    return

        self.problem = ""
        self._wake_task = asyncio.create_task(run())

    async def aclose(self) -> None:
        if self._wake_task is not None:
            self._wake_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._wake_task


def engine_api(
    app: App,
    registry: DeviceRegistry,
    confirmations: RemoteConfirmations,
    *,
    local_device_id: str = "",
) -> FastAPI:
    turn = asyncio.Lock()  # o agente atende um pedido por vez
    voice = VoiceBox(app, turn, confirmations)
    if app.bus is not None:
        voice.activity.follow(app.bus)
        app.bus.subscribe(BackgroundNotice, voice.on_notice)

    async def chat(text: str, device: Device) -> AgentResult:
        async with turn:
            log.info("pedido de %s", device.name)
            result = await app.agent.run_turn(text)
            if app.dictation is not None:
                app.dictation.requested = False  # ditado só começa em pedido feito por voz
            return result

    def lessons() -> list[dict[str, str]]:
        return [{"trigger": x.trigger, "meaning": x.meaning} for x in app.lessons.lessons()]

    def can_pair(device: Device) -> bool:
        return bool(local_device_id) and device.id == local_device_id

    api = create_device_api(
        registry=registry,
        chat=chat,
        confirmations=confirmations,
        lessons=lessons,
        voice=voice.exchange,
        can_pair=can_pair,
        address=(app.settings.devices.host, app.settings.devices.port),
    )
    add_voice_routes(api, voice)
    api.state.voice = voice
    return api


def add_voice_routes(api: FastAPI, voice: VoiceBox) -> None:
    """Histórico das conversas por voz e a chave da escuta do nome."""
    from fastapi import Depends

    from shiro.interfaces.api.devices import require_device

    paired = Depends(require_device)

    @api.get("/v1/voice/history")
    async def history(after: int = 0, current: Device = paired) -> dict[str, Any]:
        return {
            "listening": voice.listening_for_name,
            "problem": voice.problem,
            "activity": voice.activity.snapshot(),
            "items": [item for item in voice.history if item["id"] > after],
        }

    @api.get("/v1/activity")
    async def activity(current: Device = paired) -> dict[str, Any]:
        return voice.activity.snapshot()

    @api.post("/v1/voice/listening")
    async def listening(body: dict[str, bool], current: Device = paired) -> dict[str, Any]:
        try:
            await voice.set_listening(bool(body.get("enabled")))
        except Exception as exc:
            voice.problem = f"não consegui ligar a escuta: {exc}"
        return {"listening": voice.listening_for_name, "problem": voice.problem}


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
