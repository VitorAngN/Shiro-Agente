"""Auditoria append-only com hash encadeado (implementa a porta ``AuditSink``).

A cadeia em si é ``structures.hashchain``; aqui ela é gravada no SQLite.
``verify()`` lê os eventos em ordem, num cursor, e aponta o primeiro adulterado.
Gatilhos no banco impedem ``UPDATE`` e a remoção de eventos com menos de um ano.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from shiro.infrastructure.persistence.database import Database
from shiro.structures.hashchain import GENESIS, ChainRecord, ChainVerifier, link


class SqliteAuditLog:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._lock = asyncio.Lock()

    async def record(self, event_type: str, trace_id: str, payload: Mapping[str, Any]) -> None:
        payload_json = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
        ts = datetime.now(UTC).isoformat()
        connection = self._db.connection
        async with self._lock:
            async with connection.execute(
                "SELECT hash FROM audit_event ORDER BY seq DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
            prev_hash = str(row[0]) if row else GENESIS
            digest = link(prev_hash, (ts, trace_id, event_type, payload_json))
            await connection.execute(
                "INSERT INTO audit_event (ts, trace_id, event_type, payload_json, prev_hash, hash)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (ts, trace_id, event_type, payload_json, prev_hash, digest),
            )
            await connection.commit()

    async def verify(self) -> int | None:
        """``None`` se a cadeia está íntegra; senão, o ``seq`` do primeiro evento inválido.

        O primeiro evento restante pode ter ``prev_hash`` diferente do inicial,
        porque a retenção apaga os eventos mais antigos.
        """
        verifier = ChainVerifier()
        async with self._db.connection.execute(
            "SELECT seq, ts, trace_id, event_type, payload_json, prev_hash, hash"
            " FROM audit_event ORDER BY seq"
        ) as cursor:
            async for seq, ts, trace_id, event_type, payload_json, prev_hash, digest in cursor:
                fields = (ts, trace_id, event_type, payload_json)
                if not verifier.feed(ChainRecord(int(seq), fields, prev_hash, digest)):
                    break
        return verifier.broken_at

    async def count(self) -> int:
        async with self._db.connection.execute("SELECT COUNT(*) FROM audit_event") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
