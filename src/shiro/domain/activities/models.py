"""Modelo de atividades e lembretes, e as portas de persistência e agendamento."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ActivityStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


class Activity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str = Field(min_length=1)
    context: str | None = None
    due_at: datetime | None = None
    due_text: str | None = None
    status: ActivityStatus = ActivityStatus.PENDING
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


JobKind = Literal["activity_alert", "reminder"]


class Job(BaseModel):
    """Algo que o agendador dispara num momento futuro."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: JobKind
    run_at: datetime
    ref_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])


class ActivityStore(Protocol):
    async def add(self, activity: Activity) -> None: ...

    async def update(self, activity: Activity) -> None: ...

    async def get(self, activity_id: str) -> Activity | None: ...

    async def list(self, *, statuses: tuple[ActivityStatus, ...]) -> list[Activity]:
        """Atividades nesses estados, as com prazo primeiro, em ordem de prazo."""
        ...


class JobStore(Protocol):
    async def add(self, job: Job) -> None: ...

    async def due(self, now: datetime) -> list[Job]:
        """Trabalhos ativos com ``run_at <= now``, em ordem."""
        ...

    async def pending(self) -> list[Job]:
        """Todos os trabalhos ativos, vencidos ou não, em ordem de horário."""
        ...

    async def finish(self, job_id: str) -> None: ...

    async def cancel_for(self, ref_id: str, kind: JobKind) -> int: ...


def parse_offset(text: str) -> timedelta:
    """ "30m", "2h", "1d" → ``timedelta`` (validado em ``ActivitiesSettings``)."""
    amount, unit = int(text[:-1]), text[-1]
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount)}.get(
        unit, timedelta(days=amount)
    )


def offset_phrase(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return "amanhã" if days == 1 else f"em {days} dias"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "em 1 hora" if hours == 1 else f"em {hours} horas"
    return f"em {minutes} minutos"
