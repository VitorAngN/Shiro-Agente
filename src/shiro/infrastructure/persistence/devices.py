"""Aparelhos pareados no SQLite (implementa a porta ``DeviceStore``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shiro.domain.devices.models import Device
from shiro.infrastructure.persistence.database import Database

_COLUMNS = "id, name, created_at, last_seen_at, revoked_at"


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _device(row: Any) -> Device:
    return Device(
        id=row[0],
        name=row[1],
        created_at=datetime.fromisoformat(row[2]),
        last_seen_at=_when(row[3]),
        revoked_at=_when(row[4]),
    )


class SqliteDeviceStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def add(self, device: Device, token_hash: str) -> None:
        await self._db.connection.execute(
            "INSERT INTO device (id, name, token_hash, created_at, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                device.id,
                device.name,
                token_hash,
                device.created_at.isoformat(),
                device.last_seen_at.isoformat() if device.last_seen_at else None,
            ),
        )
        await self._db.connection.commit()

    async def by_token_hash(self, token_hash: str) -> Device | None:
        async with self._db.connection.execute(
            f"SELECT {_COLUMNS} FROM device WHERE token_hash = ?",  # noqa: S608 - colunas fixas
            (token_hash,),
        ) as cursor:
            row = await cursor.fetchone()
        return _device(row) if row else None

    async def list(self) -> list[Device]:
        async with self._db.connection.execute(
            f"SELECT {_COLUMNS} FROM device ORDER BY created_at DESC, id DESC"  # noqa: S608
        ) as cursor:
            return [_device(row) for row in await cursor.fetchall()]

    async def touch(self, device_id: str, seen_at: datetime) -> None:
        await self._db.connection.execute(
            "UPDATE device SET last_seen_at = ? WHERE id = ?", (seen_at.isoformat(), device_id)
        )
        await self._db.connection.commit()

    async def revoke(self, device_id: str, at: datetime) -> bool:
        cursor = await self._db.connection.execute(
            "UPDATE device SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (at.isoformat(), device_id),
        )
        await self._db.connection.commit()
        return cursor.rowcount > 0
