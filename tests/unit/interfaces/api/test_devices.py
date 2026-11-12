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
