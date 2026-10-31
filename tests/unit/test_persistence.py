from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shiro.core.events import TurnFinished
from shiro.core.models import (
    AgentResult,
    CallOutcome,
    ExecutedCall,
    RiskLevel,
    Tier,
    ToolCall,
    ToolResult,
    Usage,
)
from shiro.persistence.audit import GENESIS, SqliteAuditLog
from shiro.persistence.conversation import SqliteConversationStore
from shiro.persistence.database import Database, load_migrations


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


async def test_conversation_store_writes_turn_messages_and_tool_calls() -> None:
    database = await Database.open(":memory:")
    store = SqliteConversationStore(database)
    executed = (
        ExecutedCall(
            call=ToolCall(id="t0_0", name="set_volume", arguments={"level": 20}),
            risk=RiskLevel.R1,
            outcome=CallOutcome.ALLOWED,
            reason="permitido",
            result=ToolResult.success("Volume definido em 20%.", say="Volume em 20."),
            duration_ms=12,
        ),
        ExecutedCall(
            call=ToolCall(id="t0_1", name="format_disk", arguments={}),
            risk=None,
            outcome=CallOutcome.BLOCKED,
            reason="ferramenta desconhecida",
            result=ToolResult.failure("não existe"),
        ),
    )
    event = TurnFinished(
        trace_id="trace-1",
        session_id="session-1",
        channel="text",
        text="volume em 20",
        started_at=datetime(2026, 10, 31, 20, 0, tzinfo=UTC),
        result=AgentResult(
            text="Volume em 20.",
            tier=Tier.T0,
            calls=executed,
            usage=Usage(),
            latency_ms=40,
        ),
    )

    await store.on_turn_finished(event)
    await store.on_turn_finished(event.model_copy(update={"trace_id": "trace-2"}))

    connection = database.connection
    async with connection.execute("SELECT COUNT(*) FROM session") as cursor:
        assert (await cursor.fetchone())[0] == 1  # type: ignore[index]
    async with connection.execute(
        "SELECT role, content, tier FROM message WHERE trace_id = 'trace-1' ORDER BY role DESC"
    ) as cursor:
        messages = [tuple(row) async for row in cursor]
    assert messages == [("user", "volume em 20", None), ("assistant", "Volume em 20.", "T0")]
    async with connection.execute(
        "SELECT tool_name, risk, decision, status FROM tool_call ORDER BY tool_name"
    ) as cursor:
        calls = [tuple(row) async for row in cursor]
    assert calls[:2] == [
        ("format_disk", None, "blocked", "skipped"),
        ("format_disk", None, "blocked", "skipped"),
    ]
    assert ("set_volume", "R1", "allow", "ok") in calls
    await database.close()
