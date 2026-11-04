"""Migrações e auditoria encadeada por hash (append-only, detecta adulteração)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from shiro.infrastructure.persistence.audit import GENESIS, SqliteAuditLog
from shiro.infrastructure.persistence.database import Database, load_migrations


async def test_migrations_create_schema_and_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "shiro.db"
    database = await Database.open(path)
    latest = load_migrations()[-1][0]
    assert await database.schema_version() == latest
    assert await database.migrate() == 0
    await database.close()

    reopened = await Database.open(path)
    assert await reopened.schema_version() == latest
    await reopened.close()


async def test_audit_chain_is_verifiable_and_append_only() -> None:
    database = await Database.open(":memory:")
    audit = SqliteAuditLog(database)

    await audit.record("tool_call", "t1", {"tool": "set_volume", "args": {"level": 20}})
    await audit.record("turn", "t1", {"tier": "T0"})

    assert await audit.count() == 2
    assert await audit.verify() is None
    async with database.connection.execute(
        "SELECT prev_hash FROM audit_event ORDER BY seq"
    ) as cursor:
        rows = [row[0] async for row in cursor]
    assert rows[0] == GENESIS

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        await database.connection.execute("UPDATE audit_event SET payload_json = '{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        await database.connection.execute("DELETE FROM audit_event")
    await database.close()


async def test_audit_detects_tampering() -> None:
    database = await Database.open(":memory:")
    audit = SqliteAuditLog(database)
    for index in range(3):
        await audit.record("turn", f"t{index}", {"n": index})

    # Simula alguém com acesso direto ao arquivo: remove a proteção e edita um evento.
    connection = database.connection
    await connection.execute("DROP TRIGGER audit_event_no_update")
    await connection.execute("UPDATE audit_event SET payload_json = '{\"n\": 99}' WHERE seq = 2")
    await connection.commit()

    assert await audit.verify() == 2
    await database.close()
