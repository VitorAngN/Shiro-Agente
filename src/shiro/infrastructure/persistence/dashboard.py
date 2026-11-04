"""Consultas do painel: turnos, latência por camada, auditoria, custos, atividades e memórias."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from shiro.infrastructure.persistence.database import Database


def _percentile(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, round(share * (len(ordered) - 1)))] if ordered else 0


class DashboardQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self._db.connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def turns(self, limit: int = 50) -> list[dict[str, Any]]:
        """Turnos mais recentes: pedido, resposta, camada, tempo e cada ferramenta com a decisão."""
        replies = await self._rows(
            "SELECT a.id, a.trace_id, a.content AS reply, a.tier, a.provider, a.model,"
            " a.tokens_in, a.tokens_out, a.latency_ms, a.created_at, s.channel,"
            " (SELECT u.content FROM message u WHERE u.trace_id = a.trace_id AND u.role = 'user')"
            " AS request"
            " FROM message a JOIN session s ON s.id = a.session_id"
            " WHERE a.role = 'assistant' ORDER BY a.created_at DESC LIMIT ?",
            (limit,),
        )
        if not replies:
            return []
        calls = await self._rows(
            "SELECT message_id, tool_name, args_json, risk, decision, status, result_summary,"
            " duration_ms FROM tool_call WHERE message_id IN ("
            "  SELECT id FROM message WHERE role = 'assistant' ORDER BY created_at DESC LIMIT ?"
            ") ORDER BY finished_at",
            (limit,),
        )
        by_message: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for call in calls:
            call["args"] = json.loads(call.pop("args_json"))
            by_message[call.pop("message_id")].append(call)
        for reply in replies:
            reply["calls"] = by_message.get(reply.pop("id"), [])
        return replies

    async def stats(self, window: int = 200) -> dict[str, Any]:
        """Latência p50/p95 por camada e contagem de ações negadas ou bloqueadas."""
        rows = await self._rows(
            "SELECT tier, latency_ms FROM message WHERE role = 'assistant'"
            " ORDER BY created_at DESC LIMIT ?",
            (window,),
        )
        by_tier: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            by_tier[row["tier"] or "?"].append(row["latency_ms"] or 0)
        decisions = await self._rows(
            "SELECT decision, COUNT(*) AS n FROM tool_call GROUP BY decision"
        )
        return {
            "turns": len(rows),
            "tiers": {
                tier: {
                    "turns": len(values),
                    "p50_ms": round(statistics.median(values)),
                    "p95_ms": _percentile(values, 0.95),
                }
                for tier, values in sorted(by_tier.items())
            },
            "decisions": {row["decision"]: row["n"] for row in decisions},
        }

    async def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._rows(
            "SELECT seq, ts, trace_id, event_type, payload_json FROM audit_event"
            " ORDER BY seq DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    async def usage(self, days: int = 30) -> list[dict[str, Any]]:
        return await self._rows(
            "SELECT day, provider, model, requests, tokens_in, tokens_out, est_cost_usd"
            " FROM provider_usage ORDER BY day DESC LIMIT ?",
            (days * 4,),
        )

    async def activities(self) -> list[dict[str, Any]]:
        return await self._rows(
            "SELECT id, title, context, due_at, due_text, status, created_at FROM activity"
            " WHERE status = 'pending' ORDER BY due_at IS NULL, due_at"
        )

    async def memories(self) -> list[dict[str, Any]]:
        return await self._rows(
            "SELECT id, content, category, created_at, last_used_at FROM memory_fact"
            " ORDER BY created_at DESC"
        )
