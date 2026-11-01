"""Regras das atividades e lembretes: criar, listar, concluir, adiar, avisar.

As datas vêm sempre de ``dates.resolve`` (determinístico); a SHIRO repete a
data absoluta que entendeu em toda criação e adiamento (RF-35).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Literal

from shiro.activities import dates, matching
from shiro.activities.models import (
    Activity,
    ActivityStatus,
    ActivityStore,
    Job,
    JobStore,
    offset_phrase,
)
from shiro.core.ids import uuid7
from shiro.core.models import ToolResult
from shiro.core.ports import Clock, Notifier

Period = Literal["today", "tomorrow", "this_week", "next_week", "overdue", "all"]

_PERIOD_LABEL: dict[str, str] = {
    "today": "para hoje",
    "tomorrow": "para amanhã",
    "this_week": "nesta semana",
    "next_week": "na semana que vem",
    "overdue": "atrasadas",
    "all": "pendentes",
}
_MAX_SPOKEN = 5


class ActivityService:
    def __init__(
        self,
        *,
        store: ActivityStore,
        jobs: JobStore,
        clock: Clock,
        default_due_time: time = dates.END_OF_DAY,
        alert_offsets: Sequence[timedelta] = (timedelta(days=1), timedelta(hours=2)),
        reminder_time: time = time(9, 0),
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._clock = clock
        self._default_due_time = default_due_time
        self._offsets = tuple(alert_offsets)
        self._reminder_time = reminder_time

    # ------------------------------------------------------------ atividades

    async def create(
        self, title: str, due_text: str | None, context: str | None, utterance: str = ""
    ) -> ToolResult:
        now = self._clock.now()
        due_text = dates.ground(due_text, utterance, now=now, exclude=title)
        resolution = dates.resolve(due_text, now=now, default_time=self._default_due_time)
        if not resolution.ok:
            return ToolResult.failure(f"{resolution.problem} Nada foi anotado ainda.")
        title = title.strip().rstrip(".")
        duplicates = [
            a
            for a in matching.find(title, await self._pending())
            if a.title.casefold() == title.casefold()
        ]
        if duplicates:
            return ToolResult.failure(f"Já existe uma atividade pendente chamada {title}.")
        activity = Activity(
            id=uuid7(),
            title=title,
            context=(context or "").strip() or None,
            due_at=resolution.when,
            due_text=(due_text or "").strip() or None,
            created_at=now,
            updated_at=now,
        )
        await self._store.add(activity)
        await self._schedule_alerts(activity)
        when = self._when(activity, now)
        return ToolResult.success(f"Anotado: {title}{when}.", say=f"Anotado: {title}{when}.")

    async def list(self, period: Period) -> ToolResult:
        now = self._clock.now()
        selected = self._select(await self._pending(), period, now)
        label = _PERIOD_LABEL[period]
        if not selected:
            empty = "Nenhuma atividade atrasada." if period == "overdue" else f"Nada {label}."
            return ToolResult.success(empty, say=empty)
        items = [f"{a.title}{self._when(a, now, short=True)}" for a in selected[:_MAX_SPOKEN]]
        if len(selected) > _MAX_SPOKEN:
            items.append(f"e mais {len(selected) - _MAX_SPOKEN}")
        joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]
        noun = "atividade" if len(selected) == 1 else "atividades"
        text = f"Você tem {len(selected)} {noun} {label}: {joined}."
        return ToolResult.success(text, say=text)

    async def complete(self, query: str) -> ToolResult:
        found = await self._one(query)
        if isinstance(found, ToolResult):
            return found
        now = self._clock.now()
        await self._store.update(
            found.model_copy(
                update={"status": ActivityStatus.DONE, "completed_at": now, "updated_at": now}
            )
        )
        await self._jobs.cancel_for(found.id, "activity_alert")
        return ToolResult.success(f"Concluída: {found.title}.", say=f"Concluída: {found.title}.")

    async def postpone(self, query: str, due_text: str, utterance: str = "") -> ToolResult:
        found = await self._one(query)
        if isinstance(found, ToolResult):
            return found
        now = self._clock.now()
        base = found.due_at.astimezone(now.tzinfo) if found.due_at else None
        due_text = dates.ground(due_text, utterance, now=now, base=base) or due_text
        resolution = dates.resolve(
            due_text, now=now, default_time=self._default_due_time, base=base
        )
        if not resolution.ok or resolution.when is None:
            problem = resolution.problem or "Para quando devo adiar?"
            return ToolResult.failure(f"{problem} O prazo continua o mesmo.")
        updated = found.model_copy(
            update={"due_at": resolution.when, "due_text": due_text.strip(), "updated_at": now}
        )
        await self._store.update(updated)
        await self._jobs.cancel_for(found.id, "activity_alert")
        await self._schedule_alerts(updated)
        when = self._when(updated, now)
        return ToolResult.success(
            f"Adiada: {found.title}{when}.", say=f"Adiada: {found.title}{when}."
        )

    async def rename(self, query: str, new_title: str) -> ToolResult:
        found = await self._one(query)
        if isinstance(found, ToolResult):
            return found
        new_title = new_title.strip().rstrip(".")
        await self._store.update(
            found.model_copy(update={"title": new_title, "updated_at": self._clock.now()})
        )
        text = f"Renomeada: {found.title} agora é {new_title}."
        return ToolResult.success(text, say=text)

    async def delete(self, query: str) -> ToolResult:
        found = await self._one(query)
        if isinstance(found, ToolResult):
            return found
        await self._store.update(
            found.model_copy(
                update={"status": ActivityStatus.CANCELLED, "updated_at": self._clock.now()}
            )
        )
        await self._jobs.cancel_for(found.id, "activity_alert")
        return ToolResult.success(f"Excluída: {found.title}.", say=f"Excluída: {found.title}.")

    # ------------------------------------------------------------ lembretes

    async def remind(self, text: str, when_text: str, utterance: str = "") -> ToolResult:
        now = self._clock.now()
        when_text = dates.ground(when_text, utterance, now=now, exclude=text) or when_text
        resolution = dates.resolve(when_text, now=now, default_time=self._reminder_time)
        if not resolution.ok or resolution.when is None:
            problem = resolution.problem or "Quando devo te lembrar?"
            return ToolResult.failure(f"{problem} Nenhum lembrete foi criado.")
        text = text.strip().rstrip(".")
        await self._jobs.add(
            Job(id=uuid7(), kind="reminder", run_at=resolution.when, payload={"text": text})
        )
        when = dates.describe(resolution.when, now)
        reply = f"Combinado: te lembro de {text} {when}."
        return ToolResult.success(reply, say=reply)

    async def handle_job(self, job: Job, notifier: Notifier) -> None:
        """Dispara um aviso do agendador."""
        if job.kind == "reminder":
            await notifier.notify("Lembrete", f"Lembrete: {job.payload.get('text', '')}.")
            return
        activity = await self._store.get(job.ref_id or "")
        if activity is None or activity.status is not ActivityStatus.PENDING:
            return
        now = self._clock.now()
        when = self._when(activity, now)
        await notifier.notify("Prazo chegando", f"Prazo chegando: {activity.title}{when}.")

    # ------------------------------------------------------------ apoio

    async def _pending(self) -> list[Activity]:
        return await self._store.list(statuses=(ActivityStatus.PENDING,))

    async def _one(self, query: str) -> Activity | ToolResult:
        matches = matching.find(query, await self._pending())
        if not matches:
            return ToolResult.failure(
                f"Não encontrei nenhuma atividade pendente parecida com {query}."
            )
        if len(matches) > 1:  # títulos idênticos não existem (create impede)
            names = " ou ".join(a.title for a in matches[:3])
            return ToolResult.failure(f"Encontrei mais de uma: {names}. Qual delas?")
        return matches[0]

    async def _schedule_alerts(self, activity: Activity) -> None:
        if activity.due_at is None:
            return
        now = self._clock.now()
        for offset in self._offsets:
            run_at = activity.due_at - offset
            if run_at > now:
                await self._jobs.add(
                    Job(
                        id=uuid7(),
                        kind="activity_alert",
                        run_at=run_at,
                        ref_id=activity.id,
                        payload={"offset": offset_phrase(offset)},
                    )
                )

    def _when(self, activity: Activity, now: datetime, *, short: bool = False) -> str:
        if activity.due_at is None:
            return "" if short else ", sem prazo"
        local = activity.due_at.astimezone(now.tzinfo)
        late = " (atrasada)" if local < now else ""
        return f", {dates.describe(local, now)}{late}"

    def _select(self, pending: list[Activity], period: Period, now: datetime) -> list[Activity]:
        today = now.date()
        if period == "all":
            return pending
        if period == "overdue":
            return [a for a in pending if a.due_at is not None and a.due_at < now]
        if period == "today":
            start, end = today, today
        elif period == "tomorrow":
            start = end = today + timedelta(days=1)
        elif period == "this_week":
            # No domingo, "essa semana" é a semana que está começando.
            days_left = 6 - today.weekday() if today.weekday() < 6 else 7
            start, end = today, today + timedelta(days=days_left)
        else:
            start = today + timedelta(days=7 - today.weekday())
            end = start + timedelta(days=6)
        return [
            a
            for a in pending
            if a.due_at is not None and start <= a.due_at.astimezone(now.tzinfo).date() <= end
        ]
