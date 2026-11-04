"""Fila de prioridade: heap binário mínimo com chave e remoção preguiçosa.

Usada pelo agendador para saber qual é o próximo aviso sem consultar o banco
(``application.scheduler``).

Invariante do heap: cada entrada é menor ou igual às filhas (posições ``2i+1`` e
``2i+2``), então a menor fica sempre em ``_heap[0]``. Empates saem na ordem de
chegada (o contador ``seq`` desempata), o que torna a fila estável.

Remoção preguiçosa: tirar uma chave do meio do heap custaria O(n). Em vez disso,
a entrada é marcada como removida e descartada quando chega ao topo.

=========================  ===================
Operação                   Custo
=========================  ===================
``push``                   O(log n)
``pop``                    O(log n) amortizado
``peek``                   O(1) amortizado
``discard`` / ``in``       O(1)
=========================  ===================
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, Self


class Comparable(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...


@dataclass(order=True)
class _Entry[P: Comparable, K: Hashable]:
    priority: P
    seq: int
    key: K = field(compare=False)
    removed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Item[P: Comparable, K: Hashable]:
    priority: P
    key: K


class PriorityQueue[P: Comparable, K: Hashable]:
    """Heap mínimo de ``(prioridade, chave)``. Cada chave aparece no máximo uma vez."""

    def __init__(self) -> None:
        self._heap: list[_Entry[P, K]] = []
        self._live: dict[K, _Entry[P, K]] = {}
        self._seq = itertools.count()

    @classmethod
    def of(cls, items: Iterable[tuple[P, K]]) -> Self:
        """Monta a fila de uma vez com ``heapify``: O(n), melhor que n inserções O(n log n)."""
        queue = cls()
        for priority, key in items:
            if (old := queue._live.get(key)) is not None:
                old.removed = True  # chave repetida: vale a última
            entry = _Entry(priority, next(queue._seq), key)
            queue._live[key] = entry
            queue._heap.append(entry)
        heapq.heapify(queue._heap)
        return queue

    def push(self, priority: P, key: K) -> None:
        """Insere a chave; se ela já estava na fila, a prioridade nova substitui a antiga."""
        self.discard(key)
        entry = _Entry(priority, next(self._seq), key)
        self._live[key] = entry
        heapq.heappush(self._heap, entry)

    def discard(self, key: K) -> bool:
        """Tira a chave da fila (se estiver nela). Devolve se tirou."""
        entry = self._live.pop(key, None)
        if entry is None:
            return False
        entry.removed = True
        return True

    def peek(self) -> Item[P, K] | None:
        """A menor prioridade, sem tirar da fila; ``None`` se vazia."""
        self._drop_removed()
        if not self._heap:
            return None
        top = self._heap[0]
        return Item(top.priority, top.key)

    def pop(self) -> Item[P, K]:
        """Tira e devolve a menor prioridade. ``IndexError`` se a fila estiver vazia."""
        self._drop_removed()
        if not self._heap:
            msg = "fila de prioridade vazia"
            raise IndexError(msg)
        entry = heapq.heappop(self._heap)
        del self._live[entry.key]
        return Item(entry.priority, entry.key)

    def pop_until(self, limit: P) -> list[Item[P, K]]:
        """Tira, em ordem, todas as entradas com prioridade ``<= limit``."""
        out: list[Item[P, K]] = []
        while (top := self.peek()) is not None and not (limit < top.priority):
            out.append(self.pop())
        return out

    def priority_of(self, key: K) -> P | None:
        entry = self._live.get(key)
        return None if entry is None else entry.priority

    def _drop_removed(self) -> None:
        while self._heap and self._heap[0].removed:
            heapq.heappop(self._heap)
        # Muitas marcas acumuladas ocupam memória à toa: reconstrói em O(n).
        if len(self._heap) > 64 and len(self._heap) > 2 * len(self._live):
            self._heap = [e for e in self._heap if not e.removed]
            heapq.heapify(self._heap)

    def __len__(self) -> int:
        return len(self._live)

    def __bool__(self) -> bool:
        return bool(self._live)

    def __contains__(self, key: object) -> bool:
        return key in self._live
