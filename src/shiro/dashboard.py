"""Composição do painel: liga a API local a uma SHIRO em execução (ADR-0019)."""

from __future__ import annotations

from typing import Any

from shiro.api.queries import DashboardQueries
from shiro.api.server import Access, DashboardServer, EventFanout, create_api, url_host
from shiro.app import App
from shiro.core.events import Event


class Dashboard:
    def __init__(self, app: App) -> None:
        self._app = app
        self.access = Access()
        self._fanout = EventFanout()
        if app.bus is not None:
            app.bus.subscribe(Event, self._fanout.on_event)
        settings = app.settings.api
        self.api = create_api(
            queries=DashboardQueries(app.database),
            access=self.access,
            port=settings.port,
            status=self._status,
            fanout=self._fanout,
            verify_audit=app.audit.verify,
            routines=self._routines,
            delete_memory=app.memory.delete if app.memory is not None else None,
        )
        self.server = DashboardServer(self.api, host=settings.host, port=settings.port)

    @property
    def base_url(self) -> str:
        return f"http://{url_host(self.server.host)}:{self.server.port}"

    def login_url(self) -> str:
        return f"{self.base_url}/login?code={self.access.login_code()}"

    async def open(self) -> str:
        """Liga o servidor (se preciso) e devolve um link de entrada de uso único."""
        await self.server.start()
        return self.login_url()

    async def close(self) -> None:
        await self.server.stop()

    async def _status(self) -> dict[str, Any]:
        app = self._app
        settings = app.settings
        return {
            "local_model": app.local_llm.model,
            "cloud": app.cloud_status,
            "read_only": settings.policy.read_only_mode,
            "problems": app.problems,
            "memory": app.memory.embedder.name if app.memory is not None else None,
            "tools": list(app.registry.names()),
            "allowed_folders": list(settings.policy.allowed_folders),
            "routines": len(app.routines),
        }

    def _routines(self) -> list[dict[str, Any]]:
        return [
            {
                "name": r.name,
                "aliases": list(r.aliases),
                "description": r.description,
                "steps": [{"tool": t, "args": a} for t, a in r.calls],
            }
            for r in self._app.routines.values()
        ]
