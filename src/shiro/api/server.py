"""Servidor do painel: FastAPI em 127.0.0.1 (ADR-0019).

Segurança de um serviço só local:

* escuta só no loopback; ``Host`` diferente de 127.0.0.1/localhost é recusado
  (DNS rebinding);
* um token novo a cada execução. O navegador entra por um link de uso único
  (``/login?code=``) que grava um cookie ``HttpOnly`` e ``SameSite=Strict``;
* mudanças (``DELETE``) exigem o cabeçalho ``X-Shiro``, que um site de fora não
  consegue mandar sem o navegador bloquear;
* o WebSocket de eventos confere a ``Origin``;
* CSP sem scripts de fora nem inline, sem iframes e sem ``Referer`` (o link de
  entrada leva o código na URL).
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import secrets
import socket
import sys
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from shiro import __version__
from shiro.api.queries import DashboardQueries
from shiro.core.events import Event, ToolCallCompleted, TurnFinished, TurnStarted

COOKIE = "shiro_painel"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def url_host(host: str) -> str:
    """Como o endereço aparece numa URL (IPv6 entre colchetes)."""
    return f"[{host}]" if ":" in host else host


@dataclass
class Access:
    """Token da execução e códigos de login de uso único."""

    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    _codes: set[str] = field(default_factory=set[str])

    def login_code(self) -> str:
        code = secrets.token_urlsafe(16)
        self._codes.add(code)
        return code

    def redeem(self, code: str) -> bool:
        if code in self._codes:
            self._codes.discard(code)
            return True
        return False

    def valid(self, presented: str | None) -> bool:
        return presented is not None and hmac.compare_digest(presented, self.token)


def _event_json(event: Event) -> dict[str, Any] | None:
    if isinstance(event, TurnStarted):
        return {"type": "turn_started", "trace_id": event.trace_id, "text": event.text}
    if isinstance(event, ToolCallCompleted):
        executed = event.executed
        return {
            "type": "tool_call",
            "trace_id": event.trace_id,
            "tool": executed.call.name,
            "decision": executed.outcome.value,
            "ok": executed.result.ok,
            "duration_ms": executed.duration_ms,
        }
    if isinstance(event, TurnFinished):
        result = event.result
        return {
            "type": "turn_finished",
            "trace_id": event.trace_id,
            "tier": result.tier.value,
            "latency_ms": result.latency_ms,
            "text": result.text,
        }
    return None


class EventFanout:
    """Repassa eventos do barramento para os WebSockets abertos."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    async def on_event(self, event: Event) -> None:
        payload = _event_json(event)
        if payload is None:
            return
        for queue in list(self._queues):
            if queue.qsize() < 100:
                queue.put_nowait(payload)

    def open(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.add(queue)
        return queue

    def close(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.discard(queue)


type StatusProvider = Callable[[], Awaitable[dict[str, Any]]]
type MemoryDelete = Callable[[str], Awaitable[int]]


def create_api(
    *,
    queries: DashboardQueries,
    access: Access,
    port: int,
    status: StatusProvider,
    fanout: EventFanout,
    verify_audit: Callable[[], Awaitable[int | None]],
    routines: Callable[[], list[dict[str, Any]]],
    delete_memory: MemoryDelete | None = None,
) -> FastAPI:
    api = FastAPI(title="SHIRO", version=__version__, docs_url=None, redoc_url=None)
    names = [url_host(h) for h in LOOPBACK_HOSTS]
    allowed_hosts = {f"{h}:{port}" for h in names} | set(names)
    origins = {f"http://{h}:{port}" for h in names}
    # CSP não aceita IPv6 literal; para ::1 vale o 'self' (que cobre ws:// na mesma origem).
    sockets = " ".join(f"ws://{h}:{port}" for h in LOOPBACK_HOSTS if ":" not in h)
    headers = {
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self';"
            " font-src 'self';"
            f" connect-src 'self' {sockets}; base-uri 'none'; form-action 'none';"
            " frame-ancestors 'none'"
        ),
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }

    @api.middleware("http")
    async def only_loopback_host(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        if request.headers.get("host", "") not in allowed_hosts:
            return PlainTextResponse("host não permitido", status_code=400)
        response = await call_next(request)
        response.headers.update(headers)
        return response

    def authorized(request: Request) -> None:
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not (access.valid(request.cookies.get(COOKIE)) or access.valid(bearer or None)):
            raise HTTPException(status_code=401, detail="entre pelo link que a SHIRO abriu")

    def changing(request: Request) -> None:
        authorized(request)
        if request.headers.get("x-shiro") != "1":
            raise HTTPException(status_code=403, detail="cabeçalho X-Shiro ausente")

    auth = Depends(authorized)

    @api.get("/login")
    async def login(code: str) -> RedirectResponse:
        if not access.redeem(code):
            raise HTTPException(status_code=401, detail="link de entrada inválido ou já usado")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, access.token, httponly=True, samesite="strict")
        return response

    @api.get("/api/status", dependencies=[auth])
    async def get_status() -> dict[str, Any]:
        return {"version": __version__, **(await status())}

    @api.get("/api/turns", dependencies=[auth])
    async def get_turns(limit: int = 50) -> list[dict[str, Any]]:
        return await queries.turns(min(max(limit, 1), 500))

    @api.get("/api/stats", dependencies=[auth])
    async def get_stats() -> dict[str, Any]:
        return await queries.stats()

    @api.get("/api/audit", dependencies=[auth])
    async def get_audit(limit: int = 100) -> dict[str, Any]:
        broken = await verify_audit()
        return {"intact": broken is None, "broken_at": broken, "events": await queries.audit(limit)}

    @api.get("/api/usage", dependencies=[auth])
    async def get_usage(days: int = 30) -> list[dict[str, Any]]:
        return await queries.usage(min(max(days, 1), 365))

    @api.get("/api/activities", dependencies=[auth])
    async def get_activities() -> list[dict[str, Any]]:
        return await queries.activities()

    @api.get("/api/memories", dependencies=[auth])
    async def get_memories() -> list[dict[str, Any]]:
        return await queries.memories()

    @api.delete("/api/memories/{fact_id}", dependencies=[Depends(changing)])
    async def forget_memory(fact_id: str) -> dict[str, int]:
        if delete_memory is None:
            raise HTTPException(status_code=404, detail="memória desligada")
        return {"removed": await delete_memory(fact_id)}

    @api.get("/api/routines", dependencies=[auth])
    async def get_routines() -> list[dict[str, Any]]:
        return routines()

    @api.websocket("/api/events")
    async def events(socket: WebSocket) -> None:
        if socket.headers.get("origin") not in origins or not access.valid(
            socket.cookies.get(COOKIE)
        ):
            await socket.close(code=4401)
            return
        await socket.accept()
        queue = fanout.open()

        async def pump() -> None:
            while True:
                await socket.send_json(await queue.get())

        sender = asyncio.create_task(pump())
        try:
            # Lê só para perceber quando o navegador fecha a aba.
            while (await socket.receive())["type"] != "websocket.disconnect":
                pass
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            fanout.close(queue)

    static = Path(str(resources.files("shiro.api") / "static"))
    api.mount("/static", StaticFiles(directory=static), name="static")

    @api.get("/")
    async def index() -> FileResponse:
        return FileResponse(static / "index.html")

    return api


def bind_loopback(port: int, host: str = "127.0.0.1") -> socket.socket:
    """Abre a porta no loopback antes do uvicorn (que encerra o processo se ela estiver ocupada).

    No Windows, ``SO_EXCLUSIVEADDRUSE`` impede outro programa de "sequestrar" a porta.
    """
    if host not in LOOPBACK_HOSTS:
        msg = "o painel só escuta no loopback (127.0.0.1, ::1 ou localhost)"
        raise ValueError(msg)
    ipv6 = host == "::1"
    sock = socket.socket(socket.AF_INET6 if ipv6 else socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # pyright: ignore[reportAttributeAccessIssue]
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::1" if ipv6 else "127.0.0.1", port))
        sock.listen(16)
    except OSError:
        sock.close()
        raise
    return sock


def _server_class() -> type[Any]:
    import uvicorn

    class QuietServer(uvicorn.Server):
        """Sem tomar o Ctrl+C: quem cuida dos sinais é a SHIRO."""

        @contextlib.contextmanager
        def capture_signals(self) -> Generator[None]:
            yield

    return QuietServer


class DashboardServer:
    """Uvicorn rodando como tarefa no mesmo laço do asyncio que a SHIRO."""

    def __init__(self, api: FastAPI, *, host: str, port: int) -> None:
        import uvicorn

        if host not in LOOPBACK_HOSTS:
            msg = "o painel só escuta no loopback (127.0.0.1, ::1 ou localhost)"
            raise ValueError(msg)
        config = uvicorn.Config(
            api,
            host=host,
            port=port,
            log_config=None,  # usa o logging da SHIRO
            access_log=False,
            lifespan="off",
        )
        self._server = _server_class()(config)
        self._task: asyncio.Task[None] | None = None
        self.host, self.port = host, port

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        sock = bind_loopback(self.port, self.host)  # OSError se a porta estiver ocupada
        self._server.should_exit = False
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
        for _ in range(100):
            if self._server.started or self._task.done():
                break
            await asyncio.sleep(0.05)
        if self._task.done():
            self._task.result()  # repassa o erro (porta ocupada etc.)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(self._task, 5)
        self._task = None
