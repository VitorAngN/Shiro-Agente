"""Conexão SQLite e migrações (ADR-0007)."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import aiosqlite

MEMORY = ":memory:"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def load_migrations() -> list[tuple[int, str]]:
    """Migrações empacotadas em ``shiro.persistence.migrations``, em ordem."""
    found: list[tuple[int, str]] = []
    for entry in resources.files("shiro.infrastructure.persistence.migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match[1]), entry.read_text(encoding="utf-8")))
    return sorted(found)


class Database:
    def __init__(self, connection: aiosqlite.Connection, path: Path | None) -> None:
        self._connection = connection
        self._path = path

    @classmethod
    async def open(cls, path: Path | str) -> Database:
        """Abre (ou cria) o banco e aplica as migrações pendentes.

        Use ``":memory:"`` para um banco temporário, útil em testes.
        """
        file = None if str(path) == MEMORY else Path(path)
        if file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(file) if file else MEMORY)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        if file is not None:
            await connection.execute("PRAGMA journal_mode = WAL")
        database = cls(connection, file)
        await database.migrate()
        return database

    @property
    def connection(self) -> aiosqlite.Connection:
        return self._connection

    @property
    def path(self) -> Path | None:
        return self._path

    async def schema_version(self) -> int:
        async with self._connection.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def migrate(self) -> int:
        """Aplica migrações pendentes; devolve quantas foram aplicadas."""
        current = await self.schema_version()
        pending = [(number, sql) for number, sql in load_migrations() if number > current]
        if not pending:
            return 0
        if current > 0 and self._path is not None:
            await self._backup()
        for number, sql in pending:
            await self._connection.executescript(
                f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;"
            )
        return len(pending)

    async def _backup(self) -> None:
        if self._path is None:
            return
        backup = self._path.with_suffix(self._path.suffix + ".bak")
        backup.unlink(missing_ok=True)
        await self._connection.execute("VACUUM INTO ?", (str(backup),))

    async def close(self) -> None:
        await self._connection.close()
