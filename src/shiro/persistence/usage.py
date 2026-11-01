"""Uso diário dos provedores de nuvem (implementa a porta ``UsageLedger``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from shiro.persistence.database import Database


def _utc_today() -> date:
    return datetime.now(UTC).date()


class SqliteUsageLedger:
    """O dia é contado em UTC, como as cotas diárias dos provedores."""

    def __init__(self, database: Database, today: Callable[[], date] = _utc_today) -> None:
        self._db = database
        self._today = today

    async def today(self, provider: str) -> tuple[int, float]:
        async with self._db.connection.execute(
            "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(est_cost_usd), 0)"
            " FROM provider_usage WHERE day = ? AND provider = ?",
            (self._today().isoformat(), provider),
        ) as cursor:
            row = await cursor.fetchone()
        return (int(row[0]), float(row[1])) if row else (0, 0.0)

    async def add(
        self, provider: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float
    ) -> None:
        await self._db.connection.execute(
            "INSERT INTO provider_usage (day, provider, model, requests, tokens_in, tokens_out,"
            " est_cost_usd) VALUES (?, ?, ?, 1, ?, ?, ?)"
            " ON CONFLICT (day, provider, model) DO UPDATE SET"
            " requests = requests + 1, tokens_in = tokens_in + excluded.tokens_in,"
            " tokens_out = tokens_out + excluded.tokens_out,"
            " est_cost_usd = est_cost_usd + excluded.est_cost_usd",
            (self._today().isoformat(), provider, model, tokens_in, tokens_out, cost_usd),
        )
        await self._db.connection.commit()
