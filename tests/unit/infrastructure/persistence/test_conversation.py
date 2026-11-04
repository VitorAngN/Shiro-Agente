"""Repositório de conversas: mensagens e chamadas de ferramenta de cada turno."""

from __future__ import annotations

from datetime import UTC, datetime

from shiro.domain.events import TurnFinished
from shiro.domain.models import (
    AgentResult,
    CallOutcome,
    ExecutedCall,
    RiskLevel,
    Tier,
    ToolCall,
    ToolResult,
    Usage,
)
from shiro.infrastructure.persistence.conversation import SqliteConversationStore
from shiro.infrastructure.persistence.database import Database


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
