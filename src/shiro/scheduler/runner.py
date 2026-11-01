"""Agendador: dispara avisos de prazo e lembretes na hora certa.

Consulta os trabalhos vencidos a cada poucos segundos. Um trabalho é marcado
como feito antes de rodar, para nunca disparar duas vezes. Trabalhos que
venceram com o PC desligado disparam assim que a SHIRO volta.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from shiro.activities.models import Job, JobStore

log = logging.getLogger(__name__)

type JobHandler = Callable[[Job], Awaitable[None]]


class Scheduler:
    def __init__(
        self,
        *,
        jobs: JobStore,
        handlers: Mapping[str, JobHandler],
        clock: Callable[[], datetime],
        interval_s: float = 15.0,
    ) -> None:
        self._jobs = jobs
        self._handlers = dict(handlers)
        self._clock = clock
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    async def tick(self) -> int:
        """Roda os trabalhos vencidos; devolve quantos rodaram."""
        ran = 0
        for job in await self._jobs.due(self._clock()):
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
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("falha no agendador")
            await asyncio.sleep(self._interval_s)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="shiro-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
