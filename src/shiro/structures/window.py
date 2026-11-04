"""Janela deslizante: quantos eventos aconteceram nos últimos ``span`` segundos.

Uma fila FIFO (``deque``) de instantes em ordem crescente. Os eventos entram
pelo fim; ao contar, os que ficaram mais velhos que a janela saem pelo começo.
Cada instante entra e sai uma única vez, então o custo amortizado é O(1).

Uso: o limite de requisições por minuto da nuvem (``infrastructure.llm.guard``).

====================  ====================
Operação              Custo
====================  ====================
``add``               O(1)
``count``             O(1) amortizado
``wait_for_slot``     O(1) amortizado
====================  ====================
"""

from __future__ import annotations

from collections import deque


class SlidingWindow:
    def __init__(self, span: float) -> None:
        if span <= 0:
            msg = "a janela deslizante precisa de duração positiva"
            raise ValueError(msg)
        self.span = span
        self._events: deque[float] = deque()

    def add(self, at: float) -> None:
        if self._events and at < self._events[-1]:
            msg = "os instantes precisam chegar em ordem"
            raise ValueError(msg)
        self._events.append(at)

    def count(self, now: float) -> int:
        """Eventos em ``(now - span, now]``."""
        self._expire(now)
        return len(self._events)

    def wait_for_slot(self, now: float, limit: int) -> float:
        """Segundos até caber mais um evento sem passar de ``limit`` na janela (0 se já cabe)."""
        self._expire(now)
        if len(self._events) < limit:
            return 0.0
        oldest_that_blocks = self._events[len(self._events) - limit]
        return oldest_that_blocks + self.span - now

    def _expire(self, now: float) -> None:
        while self._events and now - self._events[0] >= self.span:
            self._events.popleft()

    def __len__(self) -> int:
        return len(self._events)
