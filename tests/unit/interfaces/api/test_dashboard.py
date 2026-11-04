"""Painel local (Fase 4, ADR-0019): consultas, autenticação e proteções de um serviço só local."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from shiro.bootstrap.app import App, build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import ApiSettings, Settings
from shiro.domain.events import ToolCallCompleted, TurnFinished, TurnStarted
from shiro.domain.models import (
    AgentResult,
    CallOutcome,
    DecisionKind,
    ExecutedCall,
    RiskLevel,
    Tier,
    ToolCall,
    ToolResult,
)
from shiro.interfaces.api.dashboard import Dashboard
from shiro.interfaces.api.server import (
    COOKIE,
    Access,
    DashboardServer,
    EventFanout,
    bind_loopback,
    create_api,
    url_host,
)
from tests.fakes.agent import SAO_PAULO, FakeProvider, reply
from tests.fakes.clock import MovableClock
from tests.fakes.desktop import FakeProbe

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)


BASE = "http://127.0.0.1:8765"


class Deny:
    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        return False


@pytest.fixture
async def app(tmp_path: Path) -> Any:
    settings = Settings.model_validate(
        {
            "policy": {"read_only_mode": False},
            "routines": {
                "estudo": {
                    "aliases": ["modo estudo"],
                    "description": "foco para estudar",
                    "steps": [{"tool": "list_activities", "args": {"period": "today"}}],
                }
            },
        }
    )
    built = await build_app(
        settings,
        confirmation=Deny(),
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=FakeProvider([reply("Tudo certo por aqui.")]),
        probe=FakeProbe(),
        clock=MovableClock(NOW),
    )
    await built.agent.run_turn("lembra que eu torço pro Coritiba")
    await built.agent.run_turn("anota prova de cálculo sexta às 10h")
    await built.agent.run_turn("como você está?")
    yield built
    await built.aclose()


@asynccontextmanager
async def client_for(
    panel: Dashboard, *, logged_in: bool = True
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=panel.api)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        if logged_in:
            response = await client.get(f"/login?code={panel.access.login_code()}")
            assert response.status_code == 303
        yield client


async def test_login_is_one_time_and_sets_a_strict_cookie(app: App) -> None:
    panel = Dashboard(app)
    async with client_for(panel, logged_in=False) as client:
        assert (await client.get("/api/status")).status_code == 401
        code = panel.access.login_code()
        first = await client.get(f"/login?code={code}")
        assert first.status_code == 303 and first.headers["location"] == "/"
        cookie = first.headers["set-cookie"].lower()
        assert f"{COOKIE}=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert (await client.get("/api/status")).status_code == 200
        reused = await client.get(f"/login?code={code}")
        assert reused.status_code == 401  # o link vale uma vez só


async def test_bearer_token_and_security_headers(app: App) -> None:
    panel = Dashboard(app)
    async with client_for(panel, logged_in=False) as client:
        wrong = await client.get("/api/status", headers={"Authorization": "Bearer errado"})
        assert wrong.status_code == 401
        ok = await client.get(
            "/api/status", headers={"Authorization": f"Bearer {panel.access.token}"}
        )
        assert ok.status_code == 200
        page = await client.get("/")
        assert page.status_code == 200 and "Painel da SHIRO" in page.text
        csp = page.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert page.headers["referrer-policy"] == "no-referrer"
        assert page.headers["x-frame-options"] == "DENY"
        script = await client.get("/static/app.js")
        assert script.status_code == 200 and "textContent" in script.text


async def test_rejects_other_hosts_against_dns_rebinding(app: App) -> None:
    panel = Dashboard(app)
    transport = httpx.ASGITransport(app=panel.api)
    async with httpx.AsyncClient(transport=transport, base_url="http://evil.example:8765") as c:
        response = await c.get("/", headers={"Authorization": f"Bearer {panel.access.token}"})
    assert response.status_code == 400


async def test_turns_stats_and_status(app: App) -> None:
    panel = Dashboard(app)
    async with client_for(panel) as client:
        status = (await client.get("/api/status")).json()
        assert status["local_model"] and status["routines"] == 1
        assert "remember_fact" in status["tools"] and status["read_only"] is False

        turns = (await client.get("/api/turns?limit=10")).json()
        assert [t["request"] for t in turns] == [
            "como você está?",
            "anota prova de cálculo sexta às 10h",
            "lembra que eu torço pro Coritiba",
        ]
        assert turns[0]["tier"] == "T1" and turns[0]["reply"] == "Tudo certo por aqui."
        memory_call = turns[2]["calls"][0]
        assert memory_call["tool_name"] == "remember_fact"
        assert memory_call["decision"] == "allow" and memory_call["args"]["text"]
        assert turns[2]["channel"] == "text"

        stats = (await client.get("/api/stats")).json()
        assert stats["turns"] == 3
        assert stats["tiers"]["T0"]["turns"] == 2 and stats["tiers"]["T1"]["turns"] == 1
        assert stats["decisions"]["allow"] == 2


async def test_activities_audit_usage_and_routines(app: App) -> None:
    panel = Dashboard(app)
    async with client_for(panel) as client:
        activities = (await client.get("/api/activities")).json()
        assert [a["title"] for a in activities] == ["prova de cálculo"]
        assert activities[0]["due_at"] == "2026-11-06T13:00:00+00:00"  # UTC; o navegador converte

        audit = (await client.get("/api/audit?limit=5")).json()
        assert audit["intact"] is True and audit["broken_at"] is None
        assert 0 < len(audit["events"]) <= 5 and "payload" in audit["events"][0]

        assert (await client.get("/api/usage")).json() == []
        routines = (await client.get("/api/routines")).json()
        assert routines == [
            {
                "name": "estudo",
                "aliases": ["modo estudo"],
                "description": "foco para estudar",
                "steps": [{"tool": "list_activities", "args": {"period": "today"}}],
            }
        ]


async def test_forgetting_a_memory_needs_the_custom_header(app: App) -> None:
    panel = Dashboard(app)
    async with client_for(panel) as client:
        memories = (await client.get("/api/memories")).json()
        assert [m["content"] for m in memories] == ["eu torço pro Coritiba"]
        target = f"/api/memories/{memories[0]['id']}"
        # Um formulário de outro site não consegue mandar cabeçalhos próprios.
        assert (await client.delete(target)).status_code == 403
        done = await client.delete(target, headers={"X-Shiro": "1"})
        assert done.json() == {"removed": 1}
        assert (await client.get("/api/memories")).json() == []


def _turn_events() -> list[Any]:
    executed = ExecutedCall(
        call=ToolCall(id="c1", name="set_volume", arguments={"level": 20}),
        risk=RiskLevel.R1,
        outcome=CallOutcome.ALLOWED,
        reason="",
        result=ToolResult(ok=True, content="ok"),
        duration_ms=12,
    )
    result = AgentResult(text="Volume em 20%.", tier=Tier.T0, calls=(executed,), latency_ms=40)
    return [
        TurnStarted(trace_id="t1", session_id="s", channel="voice", text="volume 20"),
        ToolCallCompleted(trace_id="t1", executed=executed),
        TurnFinished(
            trace_id="t1",
            session_id="s",
            channel="voice",
            text="volume 20",
            started_at=NOW,
            result=result,
        ),
    ]


def _socket_api() -> tuple[Any, Access, EventFanout]:
    access, fanout = Access(), EventFanout()

    async def status() -> dict[str, Any]:
        return {}

    async def verify() -> int | None:
        return None

    api = create_api(
        queries=None,  # type: ignore[arg-type]  # o WebSocket não consulta o banco
        access=access,
        port=8765,
        status=status,
        fanout=fanout,
        verify_audit=verify,
        routines=list,
    )
    return api, access, fanout


def test_live_events_over_websocket() -> None:
    api, access, fanout = _socket_api()
    with TestClient(api, base_url=BASE) as client:
        client.cookies.set(COOKIE, access.token)
        with client.websocket_connect("/api/events", headers={"origin": BASE}) as ws:
            for event in _turn_events():
                assert client.portal is not None
                client.portal.call(fanout.on_event, event)
            started, call, finished = (ws.receive_json() for _ in range(3))
    assert started == {"type": "turn_started", "trace_id": "t1", "text": "volume 20"}
    assert call["tool"] == "set_volume" and call["decision"] == "allow" and call["ok"]
    assert finished["tier"] == "T0" and finished["latency_ms"] == 40
    assert fanout._queues == set()  # pyright: ignore[reportPrivateUsage]  # fechou ao sair


@pytest.mark.parametrize(
    ("origin", "with_cookie"),
    [("http://evil.example", True), (BASE, False), (None, True)],
)
def test_websocket_checks_origin_and_session(origin: str | None, with_cookie: bool) -> None:
    api, access, _ = _socket_api()
    with TestClient(api, base_url=BASE) as client:
        if with_cookie:
            client.cookies.set(COOKIE, access.token)
        headers = {"origin": origin} if origin else {}
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/api/events", headers=headers),
        ):
            pass


async def test_fanout_ignores_other_events_and_caps_slow_tabs() -> None:
    fanout = EventFanout()
    queue = fanout.open()
    for _ in range(120):
        await fanout.on_event(_turn_events()[0])
    assert queue.qsize() == 100  # uma aba travada não segura memória sem limite
    fanout.close(queue)
    await fanout.on_event(_turn_events()[0])  # ninguém ouvindo: nada acontece


def test_access_codes_and_settings() -> None:
    access = Access()
    first, second = access.login_code(), access.login_code()
    assert first != second
    assert access.redeem(first) and not access.redeem(first) and access.redeem(second)
    assert access.valid(access.token) and not access.valid(None) and not access.valid("x")
    assert url_host("::1") == "[::1]" and url_host("127.0.0.1") == "127.0.0.1"
    assert ApiSettings().host == "127.0.0.1"
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({"host": "0.0.0.0"})  # noqa: S104
    with pytest.raises(ValidationError):
        ApiSettings.model_validate({"port": 80})
    api, _, _ = _socket_api()
    with pytest.raises(ValueError, match="loopback"):
        DashboardServer(api, host="0.0.0.0", port=8765)  # noqa: S104
    with pytest.raises(ValueError, match="loopback"):
        bind_loopback(8765, "192.168.0.10")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_server_listens_only_on_loopback_and_reports_a_busy_port(app: App) -> None:
    port = _free_port()
    app.settings = app.settings.model_copy(update={"api": ApiSettings(port=port)})
    panel = Dashboard(app)
    url = await panel.open()
    try:
        assert url.startswith(f"http://127.0.0.1:{port}/login?code=")
        assert await panel.open() != url  # já ligado: só gera outro link
        async with httpx.AsyncClient(trust_env=False) as client:
            entered = await client.get(url, follow_redirects=True)
            assert entered.status_code == 200 and "Painel da SHIRO" in entered.text
            status = await client.get(f"http://127.0.0.1:{port}/api/status")
            assert status.json()["version"]
        with pytest.raises(OSError):
            bind_loopback(port)  # ocupada: erro normal, sem derrubar o processo
    finally:
        await panel.close()
    assert not panel.server.running
    bind_loopback(port).close()  # liberou a porta
