"""Banco corrompido ao abrir: vai para o lado, o backup íntegro entra, e há backup diário."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shiro.infrastructure.persistence.database import BACKUP_DIR, Database, check_file


async def make_db(path: Path, rows: int) -> None:
    database = await Database.open(path)
    for i in range(rows):
        await database.connection.execute(
            "INSERT INTO session (id, channel, started_at) VALUES (?, 'text', '2026-11-04')",
            (f"s{i}",),
        )
    await database.connection.commit()
    await database.close()


def corrupt(path: Path) -> None:
    """Estraga as páginas do meio, como um disco ou um processo que escreveu por fora."""
    data = bytearray(path.read_bytes())
    assert len(data) > 8192
    data[4096:8192] = os.urandom(4096)
    path.write_bytes(bytes(data))


async def count_sessions(database: Database) -> int:
    async with database.connection.execute("SELECT COUNT(*) FROM session") as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def test_corrupt_database_is_quarantined_and_the_daily_backup_restored(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shiro.db"
    await make_db(path, 3)
    database = await Database.open(path)
    assert await database.daily_backup() is not None
    assert await database.daily_backup() is None  # um por dia
    await database.close()
    wal = tmp_path / "shiro.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0  # fechado, o WAL entrou no arquivo
    assert check_file(path) is None

    corrupt(path)
    assert check_file(path) is not None
    recovered = await Database.open(path)
    try:
        assert recovered.recovery is not None and recovered.recovery.restored_from is not None
        assert recovered.recovery.restored_from.parent.name == BACKUP_DIR
        assert await count_sessions(recovered) == 3
        assert (recovered.recovery.quarantined / "shiro.db").exists()  # nada foi apagado
        assert "corrompido" in recovered.recovery.describe()
    finally:
        await recovered.close()


async def test_without_any_backup_it_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "shiro.db"
    await make_db(path, 40)
    corrupt(path)
    database = await Database.open(path)
    try:
        assert database.recovery is not None and database.recovery.restored_from is None
        assert "banco novo" in database.recovery.describe()
        assert await count_sessions(database) == 0
    finally:
        await database.close()


async def test_daily_backups_keep_the_last_ones(tmp_path: Path) -> None:
    path = tmp_path / "shiro.db"
    await make_db(path, 1)
    folder = tmp_path / BACKUP_DIR
    folder.mkdir()
    for day in range(1, 10):
        (folder / f"shiro-2026-10-{day:02d}.db").write_bytes(b"x")
    database = await Database.open(path)
    await database.daily_backup(keep=3)
    await database.close()
    kept = sorted(p.name for p in folder.iterdir())
    assert len(kept) == 3 and kept[-1].startswith("shiro-2026-")


@pytest.mark.parametrize("garbage", [b"", b"isto nao e um banco"])
def test_check_file_reports_unreadable_files(tmp_path: Path, garbage: bytes) -> None:
    bad = tmp_path / "x.db"
    bad.write_bytes(garbage + b"\0" * 200)
    assert check_file(bad) is not None


def test_index_only_damage_is_repaired_in_place(tmp_path: Path) -> None:
    import sqlite3

    from shiro.infrastructure.persistence.database import check_file, repair_indexes

    file = tmp_path / "shiro.db"
    db = sqlite3.connect(file)
    db.executescript(
        "CREATE TABLE t (x TEXT); CREATE INDEX ix_full ON t (x);"
        "CREATE TABLE u (y TEXT); CREATE INDEX ix_empty ON u (y);"
        "INSERT INTO t VALUES ('a'), ('b'), ('c');"
    )
    roots = dict(db.execute("SELECT name, rootpage FROM sqlite_master WHERE type = 'index'"))
    db.execute("PRAGMA writable_schema = ON")  # troca as raízes: índices errados, dados intactos
    for name, other in (("ix_full", "ix_empty"), ("ix_empty", "ix_full")):
        db.execute("UPDATE sqlite_master SET rootpage = ? WHERE name = ?", (roots[other], name))
    db.commit()
    db.close()

    def damage() -> list[str]:
        with sqlite3.connect(file) as check:
            return [row[0] for row in check.execute("PRAGMA integrity_check")]

    assert "wrong # of entries in index ix_full" in damage()
    # o quick_check do Windows acusou exatamente isto no banco do motor
    assert repair_indexes(file, "wrong # of entries in index ix_full")
    assert damage() == ["ok"]
    assert check_file(file) is None
    assert sqlite3.connect(file).execute("SELECT count(*) FROM t").fetchone()[0] == 3
    assert not repair_indexes(file, "database disk image is malformed")
