"""Memória no SQLite: fatos em ``memory_fact``, vetores em ``memory_embedding`` (float32)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np

from shiro.domain.memory.embedding import Vectors
from shiro.domain.memory.models import MemoryFact
from shiro.infrastructure.persistence.database import Database


class SqliteMemoryStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, fact: MemoryFact, vector: Vectors, model: str) -> None:
        connection = self._db.connection
        await connection.execute(
            "INSERT INTO memory_fact (id, content, category, created_at) VALUES (?, ?, ?, ?)",
            (fact.id, fact.content, fact.category, fact.created_at.astimezone(UTC).isoformat()),
        )
        await connection.execute(
            "INSERT INTO memory_embedding (fact_id, vector, model) VALUES (?, ?, ?)",
            (fact.id, np.asarray(vector, dtype="<f4").tobytes(), model),
        )
        await connection.commit()

    async def all(self) -> list[MemoryFact]:
        async with self._db.connection.execute(
            "SELECT * FROM memory_fact ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            MemoryFact(
                id=row["id"],
                content=row["content"],
                category=row["category"],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_used_at=(
                    datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
                ),
            )
            for row in rows
        ]

    async def vectors(self, model: str) -> dict[str, Vectors]:
        async with self._db.connection.execute(
            "SELECT fact_id, vector FROM memory_embedding WHERE model = ?", (model,)
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["fact_id"]: np.frombuffer(row["vector"], dtype="<f4") for row in rows}

    async def set_vectors(self, items: Sequence[tuple[str, Vectors]], model: str) -> None:
        await self._db.connection.executemany(
            "INSERT INTO memory_embedding (fact_id, vector, model) VALUES (?, ?, ?)"
            " ON CONFLICT (fact_id) DO UPDATE SET vector = excluded.vector, model = excluded.model",
            [(fact_id, np.asarray(v, dtype="<f4").tobytes(), model) for fact_id, v in items],
        )
        await self._db.connection.commit()

    async def delete(self, fact_ids: Sequence[str]) -> int:
        if not fact_ids:
            return 0
        marks = ", ".join("?" for _ in fact_ids)
        cursor = await self._db.connection.execute(
            f"DELETE FROM memory_fact WHERE id IN ({marks})",  # noqa: S608 - só marcadores "?"
            tuple(fact_ids),
        )
        await self._db.connection.commit()
        return cursor.rowcount

    async def revision(self) -> int:
        # data_version muda quando OUTRA conexão grava no banco; as gravações desta
        # conexão já passam pelo serviço, que atualiza o índice na hora.
        async with self._db.connection.execute("PRAGMA data_version") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def touch(self, fact_ids: Sequence[str], when: datetime) -> None:
        stamp = when.astimezone(UTC).isoformat()
        await self._db.connection.executemany(
            "UPDATE memory_fact SET last_used_at = ? WHERE id = ?",
            [(stamp, fact_id) for fact_id in fact_ids],
        )
        await self._db.connection.commit()
