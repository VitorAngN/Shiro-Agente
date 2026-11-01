"""Atividades e lembretes: serviço, persistência, agendador e agente completo."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shiro.activities import matching
from shiro.activities.models import Activity, ActivityStatus, offset_phrase, parse_offset
from shiro.activities.service import ActivityService
from shiro.app import Desktop, build_app
from shiro.core.models import Tier
from shiro.persistence.activities import SqliteActivityStore, SqliteJobStore
from shiro.persistence.database import Database
from shiro.scheduler.runner import Scheduler
from shiro.settings import Settings
from tests.fakes import SAO_PAULO, FakeProvider, reply
from tests.unit.test_tools import FakeProbe

SUNDAY = datetime(2026, 11, 1, 10, 0, tzinfo=SAO_PAULO)


class MovableClock:
    def __init__(self, now: datetime = SUNDAY) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class Inbox:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def notify(self, title: str, message: str) -> None:
        self.messages.append(message)


@pytest.fixture
async def service() -> tuple[ActivityService, MovableClock, Database]:
    database = await Database.open(":memory:")
    clock = MovableClock()
    svc = ActivityService(
        store=SqliteActivityStore(database), jobs=SqliteJobStore(database), clock=clock
    )
    return svc, clock, database


async def test_create_repeats_the_absolute_date(
    service: tuple[ActivityService, MovableClock, Database],
) -> None:
    svc, _, db = service

    created = await svc.create("trabalho de cálculo", "pra sexta", "Cálculo 2")

    assert created.ok
    assert created.say == "Anotado: trabalho de cálculo, sexta-feira, 6 de novembro, às 23h59."
    no_deadline = await svc.create("comprar café", None, None)
    assert no_deadline.say == "Anotado: comprar café, sem prazo."
    duplicate = await svc.create("Trabalho de cálculo", "sábado", None)
    assert not duplicate.ok and "Já existe" in duplicate.content
    vague = await svc.create("prova", "semana que vem", None)
    assert not vague.ok
    assert vague.content == "Qual dia da semana que vem? Nada foi anotado ainda."
    await db.close()


async def test_list_by_period(service: tuple[ActivityService, MovableClock, Database]) -> None:
    svc, clock, db = service
    await svc.create("trabalho de cálculo", "sexta", None)
    await svc.create("prova de física", "dia 12 às 19h", None)
    await svc.create("comprar café", None, None)

    week = await svc.list("this_week")
    assert week.say == (
        "Você tem 1 atividade nesta semana: trabalho de cálculo, sexta-feira, 6 de novembro, "
        "às 23h59."
    )
    # No domingo, "semana que vem" é a semana que começa amanhã (2 a 8 de novembro).
    next_week = await svc.list("next_week")
    assert "trabalho de cálculo" in (next_week.say or "")
    assert "prova de física" not in (next_week.say or "")
    clock.current = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)  # quarta
    assert "prova de física" in ((await svc.list("next_week")).say or "")
    clock.current = SUNDAY
    everything = await svc.list("all")
    assert everything.say is not None and everything.say.startswith("Você tem 3 atividades")
    assert (await svc.list("today")).say == "Nada para hoje."

    clock.current = datetime(2026, 11, 7, 9, 0, tzinfo=SAO_PAULO)
    overdue = await svc.list("overdue")
    assert "trabalho de cálculo" in (overdue.say or "")
    assert "(atrasada)" in (overdue.say or "")
    await db.close()


async def test_complete_postpone_rename_delete(
    service: tuple[ActivityService, MovableClock, Database],
) -> None:
    svc, _, db = service
    await svc.create("prova de física", "dia 12 às 19h", None)
    await svc.create("trabalho de cálculo", "sexta", None)

    postponed = await svc.postpone("a prova de física", "semana que vem")
    assert postponed.say == "Adiada: prova de física, quinta-feira, 19 de novembro, às 19h."

    renamed = await svc.rename("trabalho de cálculo", "lista de cálculo")
    assert renamed.ok

    done = await svc.complete("o trabalho de calculo")  # sem acento, como vem do Tier 0
    assert not done.ok  # foi renomeado
    done = await svc.complete("lista de cálculo")
    assert done.say == "Concluída: lista de cálculo."

    missing = await svc.complete("redação de português")
    assert "Não encontrei" in missing.content

    deleted = await svc.delete("prova")
    assert deleted.say == "Excluída: prova de física."
    assert (await svc.list("all")).say == "Nada pendentes." or "Nada" in (
        (await svc.list("all")).say or ""
    )
    await db.close()


async def test_ambiguous_query_asks_which(
    service: tuple[ActivityService, MovableClock, Database],
) -> None:
    svc, _, db = service
    await svc.create("prova de física", "dia 12", None)
    await svc.create("prova de cálculo", "dia 13", None)

    result = await svc.complete("prova")

    assert not result.ok
    assert "Qual delas?" in result.content
    await db.close()


async def test_alerts_and_reminders_fire_on_time(
    service: tuple[ActivityService, MovableClock, Database],
) -> None:
    svc, clock, db = service
    inbox = Inbox()
    jobs = SqliteJobStore(db)

    async def on_job(job: object) -> None:
        await svc.handle_job(job, inbox)  # type: ignore[arg-type]

    scheduler = Scheduler(
        jobs=jobs, handlers={"activity_alert": on_job, "reminder": on_job}, clock=clock.now
    )
    await svc.create("trabalho de cálculo", "sexta", None)  # sexta 23h59
    reminder = await svc.remind("tirar a roupa do varal", "às 18h")
    assert reminder.say == "Combinado: te lembro de tirar a roupa do varal hoje, às 18h."

    assert await scheduler.tick() == 0

    clock.current = datetime(2026, 11, 1, 18, 0, tzinfo=SAO_PAULO)
    assert await scheduler.tick() == 1
    assert inbox.messages[-1] == "Lembrete: tirar a roupa do varal."

    clock.current = datetime(2026, 11, 5, 23, 59, tzinfo=SAO_PAULO)  # 1 dia antes
    assert await scheduler.tick() == 1
    assert inbox.messages[-1] == ("Prazo chegando: trabalho de cálculo, amanhã, às 23h59.")
    assert await scheduler.tick() == 0  # nunca dispara duas vezes

    await svc.complete("trabalho de cálculo")  # cancela o aviso de 2 h antes
    clock.current = datetime(2026, 11, 6, 22, 0, tzinfo=SAO_PAULO)
    assert await scheduler.tick() == 0
    await db.close()


async def test_scheduler_survives_a_failing_handler(
    service: tuple[ActivityService, MovableClock, Database],
) -> None:
    svc, clock, db = service

    async def broken(job: object) -> None:
        raise RuntimeError("falhou")

    scheduler = Scheduler(jobs=SqliteJobStore(db), handlers={"reminder": broken}, clock=clock.now)
    await svc.remind("beber água", "às 11h")
    clock.current = datetime(2026, 11, 1, 11, 0, tzinfo=SAO_PAULO)

    assert await scheduler.tick() == 0
    assert await scheduler.tick() == 0  # marcado como feito mesmo com falha
    scheduler.start()
    await scheduler.stop()
    await db.close()


def test_matching_and_offsets() -> None:
    now = SUNDAY
    items = [
        Activity(id="1", title="trabalho de cálculo", created_at=now, updated_at=now),
        Activity(
            id="2", title="prova de física", context="Física 3", created_at=now, updated_at=now
        ),
    ]
    assert [a.id for a in matching.find("o trabalho de calculo", items)] == ["1"]
    assert [a.id for a in matching.find("física 3", items)] == ["2"]
    assert matching.find("redação", items) == []
    assert matching.find("de", items) == []
    assert [a.id for a in matching.find("aquela prova de física", items)] == ["2"]

    assert parse_offset("1d") == timedelta(days=1)
    assert parse_offset("2h") == timedelta(hours=2)
    assert parse_offset("30m") == timedelta(minutes=30)
    assert offset_phrase(timedelta(days=1)) == "amanhã"
    assert offset_phrase(timedelta(hours=2)) == "em 2 horas"
    assert offset_phrase(timedelta(minutes=30)) == "em 30 minutos"


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


async def test_full_agent_tier0_completes_and_lists(tmp_path: Path) -> None:
    # O modelo corta o prazo ("sexta"); a ferramenta ancora na fala ("pra sexta às 10h").
    llm = FakeProvider(
        [
            reply("", ("create_activity", {"title": "trabalho de cálculo", "due_text": "sexta"})),
            reply("Anotado para sexta."),
        ]
    )
    settings = Settings.model_validate({"policy": {"read_only_mode": False}})
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=llm,
        probe=FakeProbe(),
    )
    try:
        created = await app.agent.run_turn("o trabalho de cálculo é pra sexta às 10h, anota")
        assert created.tier is Tier.T1
        assert created.calls[0].result.ok
        assert "às 10h" in created.calls[0].result.content

        noted = await app.agent.run_turn("tenho prova de física dia 12 às 19h")
        assert noted.tier is Tier.T0
        assert noted.calls[0].call.arguments == {
            "title": "prova de física",
            "due_text": "dia 12 às 19h",
        }
        assert noted.calls[0].result.ok

        listed = await app.agent.run_turn("quais são minhas atividades?")
        assert listed.tier is Tier.T0
        assert "trabalho de cálculo" in listed.text

        done = await app.agent.run_turn("terminei o trabalho de cálculo")
        assert done.tier is Tier.T0
        assert done.text == "Concluída: trabalho de cálculo."
        assert len(llm.requests) == 2  # só a primeira criação passou pelo modelo
    finally:
        await app.aclose()


async def _true() -> bool:
    return True
