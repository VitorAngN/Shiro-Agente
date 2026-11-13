"""Habilidades no SQLite (implementa a porta ``SkillStore``)."""

from __future__ import annotations

import json
from datetime import datetime

from shiro.domain.skills.models import Skill, SkillStep
from shiro.infrastructure.persistence.database import Database


class SqliteSkillStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def all(self) -> list[Skill]:
        async with self._db.connection.execute(
            "SELECT name, description, steps, created_at FROM skill ORDER BY name"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Skill(
                row[0],
                row[1],
                tuple(SkillStep(step["tool"], step.get("args", {})) for step in json.loads(row[2])),
                datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    async def put(self, skill: Skill) -> None:
        steps = json.dumps(
            [{"tool": s.tool, "args": s.args} for s in skill.steps], ensure_ascii=False
        )
        await self._db.connection.execute(
            "INSERT INTO skill (name, description, steps, created_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (name) DO UPDATE SET description = excluded.description,"
            " steps = excluded.steps, created_at = excluded.created_at",
            (skill.name, skill.description, steps, skill.created_at.isoformat()),
        )
        await self._db.connection.commit()

    async def remove(self, name: str) -> bool:
        cursor = await self._db.connection.execute("DELETE FROM skill WHERE name = ?", (name,))
        await self._db.connection.commit()
        return cursor.rowcount > 0
