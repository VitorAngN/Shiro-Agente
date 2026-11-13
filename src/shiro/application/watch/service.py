"""Esperas e vigias: "daqui a 2 minutos pausa", "quando aparecer Aceitar, clica" (ADR-0027).

Cada espera roda em segundo plano. Quando a hora chega, ou o alvo aparece na
tela, os passos rodam pela mesma política de qualquer pedido, e o resultado é
avisado em voz e no programa.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from shiro.domain.models import AgentResult

log = logging.getLogger(__name__)

type Steps = Sequence[tuple[str, Mapping[str, object]]]
type RunSteps = Callable[[Steps], Awaitable[AgentResult]]
type Seen = Callable[[str], Awaitable[bool]]
type Notify = Callable[[str], Awaitable[None]]

MAX_WAITS = 10
MIN_EVERY_S = 2.0


@dataclass
class Wait:
    id: int
    description: str
    target: str  # vazio: espera só o tempo
    steps: Steps
    due: float  # timer: quando roda; vigia: quando desiste
    every_s: float = 0.0
    checks: int = 0
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def watching(self) -> bool:
        return bool(self.target)


class Waits:
    def __init__(
        self,
        run_steps: RunSteps,
        notify: Notify,
        seen: Seen | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._run_steps = run_steps
        self._notify = notify
        self._seen = seen
        self._clock = clock
        self._waits: dict[int, Wait] = {}
        self._next_id = 1

    @property
    def can_watch(self) -> bool:
        return self._seen is not None

    def active(self) -> list[Wait]:
        return list(self._waits.values())

    def _add(self, wait: Wait, runner: Coroutine[Any, Any, None]) -> Wait | str:
        if len(self._waits) >= MAX_WAITS:
            runner.close()
            return f"Já tenho {MAX_WAITS} esperas ativas; cancele alguma antes."
        self._waits[wait.id] = wait
        self._next_id += 1
        wait.task = asyncio.get_running_loop().create_task(runner)
        wait.task.add_done_callback(lambda _t, i=wait.id: self._waits.pop(i, None))
        return wait

    def after(self, seconds: float, steps: Steps, description: str) -> Wait | str:
        wait = Wait(self._next_id, description, "", steps, self._clock() + seconds)
        return self._add(wait, self._timer(wait, seconds))

    def when_seen(
        self, target: str, steps: Steps, description: str, *, every_s: float, timeout_s: float
    ) -> Wait | str:
        if self._seen is None:
            return "Não consigo vigiar a tela agora (falta o controle do PC ou a visão)."
        wait = Wait(
            self._next_id,
            description,
            target,
            steps,
            self._clock() + timeout_s,
            every_s=max(every_s, MIN_EVERY_S),
        )
        return self._add(wait, self._watch(wait))

    def cancel(self, wait_id: int | None = None) -> int:
        """Cancela uma espera (ou todas, com ``None``); devolve quantas."""
        chosen = [w for w in self._waits.values() if wait_id is None or w.id == wait_id]
        for wait in chosen:
            if wait.task is not None:
                wait.task.cancel()
        return len(chosen)

    async def aclose(self) -> None:
        tasks = [w.task for w in self._waits.values() if w.task is not None]
        self.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _timer(self, wait: Wait, seconds: float) -> None:
        await asyncio.sleep(seconds)
        await self._fire(wait)

    async def _watch(self, wait: Wait) -> None:
        seen = self._seen
        assert seen is not None  # noqa: S101 - garantido em when_seen
        while self._clock() < wait.due:
            wait.checks += 1
            try:
                found = await seen(wait.target)
            except Exception:  # olhar a tela falhou desta vez: tenta na próxima
                log.warning("vigia %s: falha ao olhar a tela", wait.id, exc_info=True)
                found = False
            if found:
                await self._fire(wait)
                return
            await asyncio.sleep(wait.every_s)
        await self._notify(f"Desisti de esperar: {wait.description}. Não apareceu a tempo.")

    async def _fire(self, wait: Wait) -> None:
        try:
            result = await self._run_steps(wait.steps)
        except Exception as exc:
            log.exception("espera %s falhou", wait.id)
            await self._notify(f"{wait.description}: deu erro ({type(exc).__name__}).")
            return
        await self._notify(result.text or f"Feito: {wait.description}.")
