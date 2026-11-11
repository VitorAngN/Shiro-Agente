"""Pareamento por código de uso único e chave por aparelho (ADR-0022), no SQLite de verdade."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

from shiro.application.devices.service import DeviceRegistry
from shiro.domain.devices.models import clean_name, hash_token
from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.devices import SqliteDeviceStore
from tests.fakes.clock import MovableClock


@pytest.fixture
async def setup() -> AsyncIterator[tuple[DeviceRegistry, MovableClock, Database]]:
    database = await Database.open(":memory:")
    clock = MovableClock()
    yield DeviceRegistry(SqliteDeviceStore(database), clock), clock, database
    await database.close()


async def test_pairing_gives_the_device_its_own_key(
    setup: tuple[DeviceRegistry, MovableClock, Database],
) -> None:
    registry, _, database = setup
    pairing = registry.start_pairing()
    paired = await registry.complete_pairing(pairing.code, "  Meu\ncelular novo  ")

    assert paired is not None and paired.device.name == "Meu celular novo"
    device = await registry.authenticate(paired.token)
    assert device is not None and device.id == paired.device.id
    assert [d.name for d in await registry.devices()] == ["Meu celular novo"]
    # a chave não fica no banco, só o hash dela
    async with database.connection.execute("SELECT token_hash FROM device") as cursor:
        stored = [row[0] for row in await cursor.fetchall()]
    assert stored == [hash_token(paired.token)] and paired.token not in stored


async def test_a_code_works_once_and_expires(
    setup: tuple[DeviceRegistry, MovableClock, Database],
) -> None:
    registry, clock, _ = setup
    pairing = registry.start_pairing()
    assert await registry.complete_pairing(pairing.code, "A") is not None
    assert await registry.complete_pairing(pairing.code, "B") is None  # uso único

    late = registry.start_pairing()
    clock.current += timedelta(minutes=2, seconds=1)
    assert await registry.complete_pairing(late.code, "C") is None  # venceu

    old = registry.start_pairing()
    new = registry.start_pairing()
    assert await registry.complete_pairing(old.code, "D") is None  # o novo código substitui
    assert await registry.complete_pairing(new.code, "D") is not None
    assert await registry.complete_pairing("qualquer", "E") is None  # sem pareamento aberto


async def test_wrong_guesses_close_the_pairing(
    setup: tuple[DeviceRegistry, MovableClock, Database],
) -> None:
    registry, _, _ = setup
    pairing = registry.start_pairing()
    for _ in range(5):
        assert await registry.complete_pairing("chute", "X") is None
    assert await registry.complete_pairing(pairing.code, "X") is None


async def test_revoking_cuts_the_device_off_at_once(
    setup: tuple[DeviceRegistry, MovableClock, Database],
) -> None:
    registry, clock, _ = setup
    phone = await registry.complete_pairing(registry.start_pairing().code, "Celular")
    laptop = await registry.complete_pairing(registry.start_pairing().code, "Notebook")
    assert phone is not None and laptop is not None

    assert await registry.revoke(phone.device.id)
    assert not await registry.revoke(phone.device.id)  # já estava desligado
    assert await registry.authenticate(phone.token) is None
    assert await registry.authenticate(laptop.token) is not None
    assert await registry.authenticate("") is None
    assert await registry.authenticate("chave-inventada") is None
    assert [d.name for d in await registry.devices()] == ["Notebook"]

    clock.current += timedelta(minutes=5)
    await registry.authenticate(laptop.token)
    assert (await registry.devices())[0].last_seen_at == clock.current  # "visto agora"


def test_names_are_one_clean_line() -> None:
    assert clean_name("") == "Aparelho"
    assert clean_name("a\x00b\tc") == "ab c"
    assert len(clean_name("x" * 200)) == 40
