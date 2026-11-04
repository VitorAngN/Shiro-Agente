"""Agendador: dispara avisos de prazo e lembretes na hora certa.

Os horários ficam numa fila de prioridade (``structures.heap``): o laço dorme até
o próximo vencimento, ou até um trabalho novo entrar, e acorda no segundo certo.
Antes, ele consultava o banco a cada 15 s e um lembrete podia atrasar esse tanto.

O banco continua sendo a fonte da verdade. Ao acordar, os trabalhos vencidos vêm
dele, então cancelar ou concluir no banco basta: um horário cancelado que ainda
está na fila só acorda o laço à toa. O laço também nunca dorme mais que
``max_sleep_s``, para pegar trabalhos criados por outro processo (``shiro chat``
com a bandeja aberta) e os que venceram com o PC suspenso.

Um trabalho é marcado como feito antes de rodar, para nunca disparar duas vezes.
Trabalhos que venceram com o PC desligado disparam assim que a SHIRO volta.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from shiro.domain.activities.models import Job, JobKind, JobStore
from shiro.structures.heap import PriorityQueue

log = logging.getLogger(__name__)

type JobHandler = Callable[[Job], Awaitable[None]]


class Scheduler:
    def __init__(
        self,
        *,
        jobs: JobStore,
        handlers: Mapping[str, JobHandler],
        clock: Callable[[], datetime],
        max_sleep_s: float = 15.0,
    ) -> None:
        self._jobs = jobs
        self._handlers = dict(handlers)
        self._clock = clock
        self._max_sleep_s = max_sleep_s
        self._queue: PriorityQueue[datetime, str] = PriorityQueue()
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ fila

    def schedule(self, job: Job) -> None:
        """Põe o horário na fila e acorda o laço, se ele estiver dormindo além dele."""
        self._queue.push(job.run_at, job.id)
        self._changed.set()

    def watch(self, store: JobStore) -> JobStore:
        """O ``JobStore`` para os serviços: cada trabalho novo também entra na fila."""
        return WatchedJobStore(store, self)

    async def load(self) -> int:
        """Carrega na fila os trabalhos ativos do banco (na partida). Devolve quantos."""
        pending = await self._jobs.pending()
        for job in pending:
            self._queue.push(job.run_at, job.id)
        return len(pending)

    def seconds_until_next(self) -> float:
        top = self._queue.peek()
        if top is None:
            return self._max_sleep_s
        delay = (top.priority - self._clock()).total_seconds()
        return min(max(delay, 0.0), self._max_sleep_s)

    # ------------------------------------------------------------------ execução

    async def tick(self) -> int:
        """Roda os trabalhos vencidos; devolve quantos rodaram."""
        now = self._clock()
        self._queue.pop_until(now)  # a fila só diz quando acordar; o banco diz o que roda
        ran = 0
        for job in await self._jobs.due(now):
            self._queue.discard(job.id)
            await self._jobs.finish(job.id)
            handler = self._handlers.get(job.kind)
            if handler is None:
                log.warning("sem handler para trabalhos do tipo %s", job.kind)
                continue
            try:
                await handler(job)
            except Exception:
                log.exception("trabalho agendado falhou: %s", job.id)
                continue
            ran += 1
        return ran

    async def _loop(self) -> None:
        try:
            await self.load()
        except Exception:
            log.exception("agendador: não consegui carregar os trabalhos; sigo conferindo o banco")
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("falha no agendador")
            self._changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), self.seconds_until_next())

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="shiro-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def __len__(self) -> int:
        return len(self._queue)


class WatchedJobStore:
    """Decorador de ``JobStore`` (observador): avisa o agendador a cada trabalho novo."""

    def __init__(self, inner: JobStore, scheduler: Scheduler) -> None:
        self._inner = inner
        self._scheduler = scheduler

    async def add(self, job: Job) -> None:
        await self._inner.add(job)
        self._scheduler.schedule(job)

    async def due(self, now: datetime) -> list[Job]:
        return await self._inner.due(now)

    async def pending(self) -> list[Job]:
        return await self._inner.pending()

    async def finish(self, job_id: str) -> None:
        await self._inner.finish(job_id)

    async def cancel_for(self, ref_id: str, kind: JobKind) -> int:
        return await self._inner.cancel_for(ref_id, kind)
