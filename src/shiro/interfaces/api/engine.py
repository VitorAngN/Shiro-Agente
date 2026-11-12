"""O motor como serviço (ADR-0022): a API dos aparelhos rodando junto do agente.

``shiro serve`` sobe o agente e a API. O programa do PC entra com a chave do
aparelho "Este PC", criada na primeira execução e guardada na pasta de dados do
usuário, com a mesma proteção do banco.
"""

from __future__ import annotations

import asyncio
import contextlib
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


def engine_api(app: App, registry: DeviceRegistry, confirmations: RemoteConfirmations) -> FastAPI:
    turn = asyncio.Lock()  # o agente atende um pedido por vez

    async def chat(text: str, device: Device) -> AgentResult:
        async with turn:
            log.info("pedido de %s", device.name)
            return await app.agent.run_turn(text)

    def lessons() -> list[dict[str, str]]:
        return [{"trigger": x.trigger, "meaning": x.meaning} for x in app.lessons.lessons()]

    return create_device_api(
        registry=registry, chat=chat, confirmations=confirmations, lessons=lessons
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
