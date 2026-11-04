"""Agendador sobre a fila de prioridade: acorda no segundo certo, e o banco decide o que roda."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

from shiro.application.scheduler import Scheduler
from shiro.domain.activities.models import Job
from shiro.infrastructure.persistence.activities import SqliteJobStore
from shiro.infrastructure.persistence.database import Database
from tests.fakes.agent import SAO_PAULO
from tests.fakes.clock import MovableClock

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)


def job(job_id: str, minutes: float) -> Job:
    return Job(id=job_id, kind="reminder", run_at=NOW + timedelta(minutes=minutes))


async def test_queue_orders_wakeups_and_the_database_decides() -> None:
    database = await Database.open(":memory:")
    clock = MovableClock(NOW)
    ran: list[str] = []

    async def handle(done: Job) -> None:
        ran.append(done.id)

    raw = SqliteJobStore(database)
    scheduler = Scheduler(jobs=raw, handlers={"reminder": handle}, clock=clock.now, max_sleep_s=60)
    jobs = scheduler.watch(raw)
    assert scheduler.seconds_until_next() == 60  # nada na fila: só a conferência periódica

    await jobs.add(job("b", 10))
    await jobs.add(job("a", 2))
    await jobs.add(job("c", 0.5))
    assert len(scheduler) == 3
    assert scheduler.seconds_until_next() == 30  # o "c", daqui a meio minuto

    await jobs.cancel_for("x", "reminder")  # nada a ver: a fila continua igual
    clock.current = NOW + timedelta(minutes=3)
    assert scheduler.seconds_until_next() == 0
    assert await scheduler.tick() == 2 and ran == ["c", "a"]
    assert len(scheduler) == 1 and scheduler.seconds_until_next() == 60  # "b" daqui a 7 min > 60 s
    await database.close()


async def test_load_brings_back_jobs_saved_before_a_restart() -> None:
    database = await Database.open(":memory:")
    store = SqliteJobStore(database)
    await store.add(job("antigo", 5))
    await store.add(job("outro", 1))
    scheduler = Scheduler(jobs=store, handlers={}, clock=MovableClock(NOW).now, max_sleep_s=600)
    assert await scheduler.load() == 2
    assert scheduler.seconds_until_next() == 60
    await database.close()


async def test_loop_fires_on_time_without_polling() -> None:
    """Com conferência a cada 30 s, um lembrete de 0,3 s só dispara a tempo pela fila."""
    database = await Database.open(":memory:")
    fired: list[float] = []
    started = time.monotonic()

    async def handle(_: Job) -> None:
        fired.append(time.monotonic() - started)

    raw = SqliteJobStore(database)
    scheduler = Scheduler(
        jobs=raw,
        handlers={"reminder": handle},
        clock=lambda: datetime.now(SAO_PAULO),
        max_sleep_s=30,
    )
    scheduler.start()
    try:
        await asyncio.sleep(0.05)  # o laço já está dormindo
        run_at = datetime.now(SAO_PAULO) + timedelta(seconds=0.3)
        await scheduler.watch(raw).add(Job(id="j", kind="reminder", run_at=run_at))
        for _ in range(60):
            if fired:
                break
            await asyncio.sleep(0.05)
    finally:
        await scheduler.stop()
        await database.close()
    assert len(fired) == 1 and 0.25 <= fired[0] < 1.5
