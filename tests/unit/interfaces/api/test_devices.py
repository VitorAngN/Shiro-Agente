"""API dos aparelhos (ADR-0022): só entra quem pareou, e cada chave vale para um aparelho."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shiro.application.devices.service import DeviceRegistry
from shiro.domain.devices.models import Device
from shiro.domain.models import AgentResult, Tier
from shiro.interfaces.api.devices import create_device_api
from tests.fakes.clock import MovableClock


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[Device, str]] = {}

    async def add(self, device: Device, token_hash: str) -> None:
        self.rows[device.id] = (device, token_hash)

    async def by_token_hash(self, token_hash: str) -> Device | None:
        return next((d for d, h in self.rows.values() if h == token_hash), None)

    async def list(self) -> list[Device]:
        return [d for d, _ in self.rows.values()]

    async def touch(self, device_id: str, seen_at: datetime) -> None:
        return None

    async def revoke(self, device_id: str, at: datetime) -> bool:
        device, token_hash = self.rows[device_id]
        if not device.active:
            return False
        self.rows[device_id] = (
            Device(device.id, device.name, device.created_at, None, at),
            token_hash,
        )
        return True


@pytest.fixture
def setup() -> Iterator[tuple[TestClient, DeviceRegistry, list[tuple[str, str]]]]:
    registry = DeviceRegistry(MemoryStore(), MovableClock())
    asked: list[tuple[str, str]] = []

    async def chat(text: str, device: Device) -> AgentResult:
        asked.append((device.name, text))
        return AgentResult(text="São 10 horas.", tier=Tier.T0, latency_ms=12)

    with TestClient(create_device_api(registry=registry, chat=chat)) as client:
        yield client, registry, asked


def pair(client: TestClient, registry: DeviceRegistry, name: str = "Celular") -> dict[str, str]:
    code = registry.start_pairing().code
    response = client.post("/v1/pair", json={"code": code, "name": name})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_everything_but_pairing_needs_the_device_key(
    setup: tuple[TestClient, DeviceRegistry, list[tuple[str, str]]],
) -> None:
    client, _, asked = setup
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/devices").status_code == 401
    assert client.post("/v1/chat", json={"text": "que horas são"}).status_code == 401
    wrong = {"Authorization": "Bearer chave-inventada"}
    assert client.post("/v1/chat", json={"text": "oi"}, headers=wrong).status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert asked == []


def test_pairing_then_chatting(
    setup: tuple[TestClient, DeviceRegistry, list[tuple[str, str]]],
) -> None:
    client, registry, asked = setup
    assert client.post("/v1/pair", json={"code": "chute", "name": "X"}).status_code == 403
    auth = pair(client, registry)

    assert client.get("/v1/me", headers=auth).json()["name"] == "Celular"
    reply = client.post("/v1/chat", json={"text": "que horas são"}, headers=auth).json()
    assert reply == {"text": "São 10 horas.", "tier": "T0", "latency_ms": 12, "tools": []}
    assert asked == [("Celular", "que horas são")]
    too_long = client.post("/v1/chat", json={"text": "a" * 2001}, headers=auth)
    assert too_long.status_code == 422 and len(asked) == 1


def test_a_device_that_leaves_loses_access_and_the_others_keep_it(
    setup: tuple[TestClient, DeviceRegistry, list[tuple[str, str]]],
) -> None:
    client, registry, _ = setup
    phone, laptop = pair(client, registry), pair(client, registry, "Notebook")
    assert {d["name"] for d in client.get("/v1/devices", headers=phone).json()} == {
        "Celular",
        "Notebook",
    }
    assert client.delete("/v1/me", headers=phone).json() == {"revoked": True}
    assert client.get("/v1/me", headers=phone).status_code == 401
    assert [d["name"] for d in client.get("/v1/devices", headers=laptop).json()] == ["Notebook"]


async def test_confirmations_wait_for_the_client_and_default_to_no() -> None:
    import asyncio

    from shiro.application.devices.confirmations import RemoteConfirmations
    from shiro.domain.models import DecisionKind

    confirmations = RemoteConfirmations(timeout_s=0.05)
    assert await confirmations.ask("Abrir a Steam?", DecisionKind.CONFIRM_VOICE) is False  # venceu
    assert confirmations.pending() == []

    confirmations = RemoteConfirmations(timeout_s=5)
    asking = asyncio.create_task(confirmations.ask("Abrir a Steam?", DecisionKind.CONFIRM_VOICE))
    await asyncio.sleep(0)
    (pending,) = confirmations.pending()
    assert pending.prompt == "Abrir a Steam?"
    assert confirmations.answer(pending.id, True)
    assert await asking is True
    assert not confirmations.answer(pending.id, True)  # já respondida


def test_confirmation_and_lesson_routes(
    setup: tuple[TestClient, DeviceRegistry, list[tuple[str, str]]],
) -> None:
    client, registry, _ = setup
    auth = pair(client, registry)
    assert client.get("/v1/confirmations").status_code == 401
    assert client.get("/v1/confirmations", headers=auth).json() == []
    missing = client.post("/v1/confirmations/x", json={"approve": True}, headers=auth)
    assert missing.status_code == 404
    assert client.get("/v1/lessons", headers=auth).json() == []


async def test_the_local_program_key_is_created_once_and_reused(tmp_path: Path) -> None:
    from shiro.interfaces.api.engine import LOCAL_TOKEN_FILE, ensure_local_token

    registry = DeviceRegistry(MemoryStore(), MovableClock())
    token = await ensure_local_token(registry, tmp_path)
    assert (tmp_path / LOCAL_TOKEN_FILE).read_text("utf-8") == token
    assert await ensure_local_token(registry, tmp_path) == token
    assert [d.name for d in await registry.devices()] == ["Este PC"]

    (device,) = await registry.devices()
    await registry.revoke(device.id)  # desligado pelo usuário: a próxima execução cria outra
    assert await ensure_local_token(registry, tmp_path) != token


def test_launch_spec_tells_the_program_how_to_start_the_engine(tmp_path: Path) -> None:
    import json

    from shiro.interfaces.api.engine import ENGINE_FILE, write_launch_spec

    write_launch_spec(tmp_path)
    spec = json.loads((tmp_path / ENGINE_FILE).read_text("utf-8"))
    assert Path(spec["exe"]).name.startswith("python") and spec["args"][0] == "-c"
    assert "serve" in spec["args"][1]


def test_only_the_pc_program_opens_a_pairing_or_unlinks_others() -> None:
    registry = DeviceRegistry(MemoryStore(), MovableClock())
    local: list[str] = []

    async def chat(text: str, device: Device) -> AgentResult:
        return AgentResult(text="ok", tier=Tier.T0)

    async def voice(device: Device) -> tuple[str, AgentResult] | None:
        return ("que horas são", AgentResult(text="São 10 horas.", tier=Tier.T0))

    api = create_device_api(
        registry=registry,
        chat=chat,
        voice=voice,
        can_pair=lambda device: device.id in local,
        address=("100.101.102.103", 8766),
    )
    with TestClient(api) as client:
        pc, phone = pair(client, registry, "Este PC"), pair(client, registry, "Celular")
        ids = {d["name"]: d["id"] for d in client.get("/v1/devices", headers=pc).json()}
        local.append(ids["Este PC"])

        assert client.post("/v1/pairing", headers=phone).status_code == 403
        opened = client.post("/v1/pairing", headers=pc).json()
        assert (opened["host"], opened["port"]) == ("100.101.102.103", 8766)
        joined = client.post("/v1/pair", json={"code": opened["code"], "name": "Tablet"})
        assert joined.status_code == 200  # o código do QR pareia outro aparelho

        spoken = client.post("/v1/voice", headers=phone).json()
        assert spoken["heard"] == "que horas são" and spoken["text"] == "São 10 horas."

        assert client.delete(f"/v1/devices/{ids['Celular']}", headers=phone).status_code == 403
        assert client.delete(f"/v1/devices/{ids['Este PC']}", headers=pc).status_code == 400
        assert client.delete(f"/v1/devices/{ids['Celular']}", headers=pc).json() == {
            "revoked": True
        }
        assert client.get("/v1/me", headers=phone).status_code == 401


def test_voice_is_optional(setup: tuple[TestClient, DeviceRegistry, list[tuple[str, str]]]) -> None:
    client, registry, _ = setup
    assert client.post("/v1/voice", headers=pair(client, registry)).status_code == 503


async def test_voice_box_answers_after_the_name_and_keeps_history() -> None:
    import asyncio
    from types import SimpleNamespace

    from shiro.interfaces.api.engine import VoiceBox

    said: list[str] = []

    class Session:
        _stt = None

        async def listen(self) -> str | None:
            return "que horas são"

        async def say(self, text: str) -> bool:
            said.append(text)
            return True

    async def run_turn(text: str) -> AgentResult:
        return AgentResult(text=f"resposta para {text}", tier=Tier.T0)

    app = SimpleNamespace(agent=SimpleNamespace(run_turn=run_turn))
    box = VoiceBox(app, asyncio.Lock())  # type: ignore[arg-type]

    async def ready() -> Session:
        return Session()

    box._ready = ready  # type: ignore[method-assign] # pyright: ignore[reportPrivateUsage]
    box.command("abre a steam")  # "Shiro, abre a steam" numa frase só
    await asyncio.sleep(0.01)
    box.wake()  # só "Shiro": escuta o pedido em seguida
    await asyncio.sleep(0.01)

    assert [item["heard"] for item in box.history] == ["abre a steam", "que horas são"]
    assert {item["source"] for item in box.history} == {"nome"}
    assert said == ["resposta para abre a steam", "resposta para que horas são"]
    assert not box.listening_for_name


def test_voice_routes_take_no_stray_query() -> None:
    """Regressão: ``request`` sem tipo resolvido virava parâmetro obrigatório (422 em laço)."""
    from fastapi import FastAPI

    from shiro.interfaces.api.engine import add_voice_routes

    api = FastAPI()
    add_voice_routes(api, object())  # type: ignore[arg-type]
    from fastapi.routing import APIRoute

    voice = [r for r in api.routes if isinstance(r, APIRoute) and r.path.startswith("/v1/voice")]
    assert len(voice) == 2
    for route in voice:
        assert "request" not in {p.name for p in route.dependant.query_params}


async def test_activity_follows_the_turn() -> None:
    from shiro.application.bus import EventBus
    from shiro.domain.events import TurnProgress, TurnStarted
    from shiro.interfaces.api.engine import Activity

    now = [100.0]
    activity = Activity(clock=lambda: now[0])
    bus = EventBus()
    activity.follow(bus)
    assert activity.snapshot()["stage"] == "idle"
    await bus.publish(TurnStarted(trace_id="t", session_id="s", channel="api", text="oi"))
    now[0] = 103.0
    await bus.publish(TurnProgress(trace_id="t", stage="tool", detail="Abrir youtube.com"))
    now[0] = 104.5
    snap = activity.snapshot()
    assert snap == {
        "stage": "tool",
        "detail": "Abrir youtube.com",
        "seconds": 1.5,
        "total_seconds": 4.5,
    }
    activity.idle()
    assert activity.snapshot()["total_seconds"] == 0.0
