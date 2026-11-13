"""Conexão SQLite, migrações e proteção contra banco corrompido (ADR-0007).

Ao abrir, o arquivo passa por ``PRAGMA quick_check``. Corrompido, ele vai para
``corrompido-<data>/`` ao lado (nada é apagado) e o backup íntegro mais recente
entra no lugar: o de antes da última migração (``shiro.db.bak``) ou um dos
backups diários (``backups/shiro-AAAA-MM-DD.db``, os últimos 7).
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

MEMORY = ":memory:"
BACKUP_DIR = "backups"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_COMPANIONS = ("-wal", "-shm")


@dataclass(frozen=True)
class Recovery:
    """O que aconteceu ao abrir um banco corrompido."""

    problem: str
    quarantined: Path
    restored_from: Path | None

    def describe(self) -> str:
        where = (
            f"voltei o backup {self.restored_from.name}"
            if self.restored_from
            else "não havia backup íntegro; comecei um banco novo"
        )
        return f"banco corrompido ({self.problem}); guardei em {self.quarantined.name} e {where}"


def check_file(file: Path) -> str | None:
    """``None`` se o arquivo SQLite está íntegro; senão, o problema encontrado."""
    try:
        connection = sqlite3.connect(f"file:{file.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return str(exc)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        return None if result and result[0] == "ok" else str(result[0] if result else "vazio")
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        connection.close()


def _backups_newest_first(file: Path) -> list[Path]:
    daily = sorted((file.parent / BACKUP_DIR).glob(f"{file.stem}-*.db"), reverse=True)
    before_migration = file.with_suffix(file.suffix + ".bak")
    found = [before_migration] if before_migration.exists() else []
    found += daily
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


_INDEX_ONLY = re.compile(r"^(?:wrong # of entries in index|row \d+ missing from index) ")


def repair_indexes(file: Path, problem: str) -> bool:
    """Só os índices estragados (os dados estão bons): ``REINDEX`` resolve sem perder nada."""
    lines = [line for line in problem.splitlines() if line.strip()]
    if not lines or not all(_INDEX_ONLY.match(line) for line in lines):
        return False
    try:
        connection = sqlite3.connect(str(file))
        try:
            connection.execute("REINDEX")
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return check_file(file) is None


def recover(file: Path, problem: str) -> Recovery:
    """Põe o banco corrompido de lado e restaura o backup íntegro mais novo (síncrono)."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    quarantine = file.parent / f"corrompido-{stamp}"
    quarantine.mkdir(parents=True, exist_ok=True)
    for path in (file, *(file.with_name(file.name + s) for s in _COMPANIONS)):
        if path.exists():
            shutil.move(str(path), quarantine / path.name)
    for backup in _backups_newest_first(file):
        if check_file(backup) is None:
            shutil.copy2(backup, file)
            return Recovery(problem, quarantine, backup)
    return Recovery(problem, quarantine, None)


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
        self.recovery: Recovery | None = None

    @classmethod
    async def open(cls, path: Path | str) -> Database:
        """Abre (ou cria) o banco e aplica as migrações pendentes.

        Use ``":memory:"`` para um banco temporário, útil em testes.
        """
        file = None if str(path) == MEMORY else Path(path)
        recovery: Recovery | None = None
        if file is not None:
            file.parent.mkdir(parents=True, exist_ok=True)
            if file.exists() and (problem := await asyncio.to_thread(check_file, file)):
                if await asyncio.to_thread(repair_indexes, file, problem):
                    log.warning("banco: índices refeitos (%s); nenhum dado perdido", problem)
                else:
                    recovery = await asyncio.to_thread(recover, file, problem)
                    log.error("banco: %s", recovery.describe())
        connection = await aiosqlite.connect(str(file) if file else MEMORY)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        if file is not None:
            await connection.execute("PRAGMA journal_mode = WAL")
        database = cls(connection, file)
        database.recovery = recovery
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

    async def daily_backup(self, keep: int = 7) -> Path | None:
        """Uma cópia íntegra por dia em ``backups/`` (``VACUUM INTO``); mantém ``keep`` últimas."""
        if self._path is None:
            return None
        folder = self._path.parent / BACKUP_DIR
        folder.mkdir(exist_ok=True)
        target = folder / f"{self._path.stem}-{datetime.now(UTC):%Y-%m-%d}.db"
        if target.exists():
            return None
        await self._connection.execute("VACUUM INTO ?", (str(target),))
        for old in sorted(folder.glob(f"{self._path.stem}-*.db"), reverse=True)[keep:]:
            old.unlink(missing_ok=True)
        return target

    async def close(self) -> None:
        if self._path is not None:
            # Junta o WAL no arquivo principal: fechado, o banco fica num arquivo só.
            await self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await self._connection.close()
