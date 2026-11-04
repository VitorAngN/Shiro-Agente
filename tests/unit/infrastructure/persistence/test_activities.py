"""Repositório de atividades no SQLite."""

from __future__ import annotations

from shiro.domain.activities.models import Activity, ActivityStatus
from shiro.infrastructure.persistence.activities import SqliteActivityStore
from shiro.infrastructure.persistence.database import Database
from tests.fakes.clock import SUNDAY


async def test_status_survives_round_trip() -> None:
    database = await Database.open(":memory:")
    store = SqliteActivityStore(database)
    activity = Activity(id="x", title="t", due_at=SUNDAY, created_at=SUNDAY, updated_at=SUNDAY)
    await store.add(activity)
    await store.update(activity.model_copy(update={"status": ActivityStatus.DONE}))

    loaded = await store.get("x")
    assert loaded is not None
    assert loaded.status is ActivityStatus.DONE
    assert loaded.due_at == SUNDAY
    assert await store.get("nope") is None
    await database.close()
