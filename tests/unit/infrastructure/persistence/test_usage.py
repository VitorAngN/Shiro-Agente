"""Uso da nuvem por dia e modelo."""

from __future__ import annotations

from datetime import date

import pytest

from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.usage import SqliteUsageLedger


async def test_sqlite_ledger_accumulates_per_day() -> None:
    database = await Database.open(":memory:")
    day = [date(2026, 11, 1)]
    ledger = SqliteUsageLedger(database, today=lambda: day[0])

    await ledger.add("gemini", "m", 100, 10, 0.001)
    await ledger.add("gemini", "m", 50, 5, 0.002)
    await ledger.add("outro", "m", 1, 1, 1.0)

    requests, cost = await ledger.today("gemini")
    assert requests == 2
    assert cost == pytest.approx(0.003)
    day[0] = date(2026, 11, 2)
    assert await ledger.today("gemini") == (0, 0.0)
    await database.close()
