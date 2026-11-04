"""Histórico de conversas: grava cada turno a partir do evento ``TurnFinished``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from shiro.domain.events import TurnFinished
from shiro.domain.ids import uuid7
from shiro.domain.models import CallOutcome, ExecutedCall
from shiro.infrastructure.persistence.database import Database

_SUMMARY_LIMIT = 500


def _status(executed: ExecutedCall) -> str:
    if executed.outcome in {CallOutcome.BLOCKED, CallOutcome.DENIED}:
        return "skipped"
    return "ok" if executed.result.ok else "error"


class SqliteConversationStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def on_turn_finished(self, event: TurnFinished) -> None:
        connection = self._db.connection
        result = event.result
        started = event.started_at.astimezone(UTC).isoformat()
        finished = datetime.now(UTC).isoformat()

        await connection.execute(
            "INSERT OR IGNORE INTO session (id, channel, started_at) VALUES (?, ?, ?)",
            (event.session_id, event.channel, started),
        )
        await connection.execute(
            "INSERT INTO message (id, session_id, trace_id, role, content, created_at)"
            " VALUES (?, ?, ?, 'user', ?, ?)",
            (uuid7(), event.session_id, event.trace_id, event.text, started),
        )
        assistant_id = uuid7()
        await connection.execute(
            "INSERT INTO message (id, session_id, trace_id, role, content, tier, provider, model,"
            " tokens_in, tokens_out, latency_ms, created_at)"
            " VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assistant_id,
                event.session_id,
                event.trace_id,
                result.text,
                result.tier.value,
                result.provider,
                result.model,
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
                result.latency_ms,
                finished,
            ),
        )
        await connection.executemany(
            "INSERT INTO tool_call (id, message_id, tool_name, args_json, risk, decision, status,"
            " result_summary, duration_ms, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    uuid7(),
                    assistant_id,
                    executed.call.name,
                    json.dumps(executed.call.arguments, ensure_ascii=False, sort_keys=True),
                    executed.risk.value if executed.risk else None,
                    executed.outcome.value,
                    _status(executed),
                    executed.result.content[:_SUMMARY_LIMIT],
                    executed.duration_ms,
                    finished,
                )
                for executed in result.calls
            ],
        )
        await connection.commit()
