"""Lições do usuário no SQLite (implementa a porta ``LessonStore``)."""

from __future__ import annotations

from datetime import datetime

from shiro.domain.learning.models import Lesson
from shiro.infrastructure.persistence.database import Database


class SqliteLessonStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def all(self) -> list[Lesson]:
        async with self._db.connection.execute(
            "SELECT trigger, meaning, created_at FROM lesson ORDER BY trigger"
        ) as cursor:
            return [
                Lesson(row[0], row[1], datetime.fromisoformat(row[2]))
                for row in await cursor.fetchall()
            ]

    async def put(self, lesson: Lesson) -> None:
        await self._db.connection.execute(
            "INSERT INTO lesson (trigger, meaning, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT (trigger) DO UPDATE SET meaning = excluded.meaning,"
            " created_at = excluded.created_at",
            (lesson.trigger, lesson.meaning, lesson.created_at.isoformat()),
        )
        await self._db.connection.commit()

    async def remove(self, trigger: str) -> bool:
        cursor = await self._db.connection.execute(
            "DELETE FROM lesson WHERE trigger = ?", (trigger,)
        )
        await self._db.connection.commit()
        return cursor.rowcount > 0
