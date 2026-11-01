"""Atividades e trabalhos agendados no SQLite (implementa ``ActivityStore`` e ``JobStore``)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from shiro.activities.models import Activity, ActivityStatus, Job, JobKind
from shiro.persistence.database import Database


def _utc(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _activity(row: aiosqlite.Row) -> Activity:
    return Activity(
        id=row["id"],
        title=row["title"],
        context=row["context"],
        due_at=_parse(row["due_at"]),
        due_text=row["due_text"],
        status=ActivityStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=_parse(row["completed_at"]),
    )


class SqliteActivityStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, activity: Activity) -> None:
        await self._db.connection.execute(
            "INSERT INTO activity (id, title, context, due_at, due_text, status, created_at,"
            " updated_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            self._values(activity),
        )
        await self._db.connection.commit()

    async def update(self, activity: Activity) -> None:
        values = self._values(activity)
        await self._db.connection.execute(
            "UPDATE activity SET title = ?, context = ?, due_at = ?, due_text = ?, status = ?,"
            " created_at = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (*values[1:], values[0]),
        )
        await self._db.connection.commit()

    async def get(self, activity_id: str) -> Activity | None:
        async with self._db.connection.execute(
            "SELECT * FROM activity WHERE id = ?", (activity_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _activity(row) if row else None

    async def list(self, *, statuses: tuple[ActivityStatus, ...]) -> list[Activity]:
        marks = ", ".join("?" for _ in statuses)
        async with self._db.connection.execute(
            f"SELECT * FROM activity WHERE status IN ({marks})"  # noqa: S608 - só placeholders
            " ORDER BY due_at IS NULL, due_at, created_at",
            tuple(status.value for status in statuses),
        ) as cursor:
            return [_activity(row) async for row in cursor]

    @staticmethod
    def _values(activity: Activity) -> tuple[Any, ...]:
        return (
            activity.id,
            activity.title,
            activity.context,
            _utc(activity.due_at),
            activity.due_text,
            activity.status.value,
            _utc(activity.created_at),
            _utc(activity.updated_at),
            _utc(activity.completed_at),
        )


class SqliteJobStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, job: Job) -> None:
        await self._db.connection.execute(
            "INSERT INTO scheduled_job (id, kind, ref_id, payload_json, run_at, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', ?)",
            (
                job.id,
                job.kind,
                job.ref_id,
                json.dumps(job.payload, ensure_ascii=False),
                _utc(job.run_at),
                datetime.now(UTC).isoformat(),
            ),
        )
        await self._db.connection.commit()

    async def due(self, now: datetime) -> list[Job]:
        async with self._db.connection.execute(
            "SELECT id, kind, ref_id, payload_json, run_at FROM scheduled_job"
            " WHERE status = 'active' AND run_at <= ? ORDER BY run_at",
            (_utc(now),),
        ) as cursor:
            return [
                Job(
                    id=row["id"],
                    kind=row["kind"],
                    ref_id=row["ref_id"],
                    payload=json.loads(row["payload_json"]),
                    run_at=datetime.fromisoformat(row["run_at"]),
                )
                async for row in cursor
            ]

    async def finish(self, job_id: str) -> None:
        await self._db.connection.execute(
            "UPDATE scheduled_job SET status = 'done' WHERE id = ?", (job_id,)
        )
        await self._db.connection.commit()

    async def cancel_for(self, ref_id: str, kind: JobKind) -> int:
        cursor = await self._db.connection.execute(
            "UPDATE scheduled_job SET status = 'cancelled'"
            " WHERE ref_id = ? AND kind = ? AND status = 'active'",
            (ref_id, kind),
        )
        await self._db.connection.commit()
        return cursor.rowcount
