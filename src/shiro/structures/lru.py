"""Cache LRU (menos usado recentemente) com capacidade fixa.

Tabela hash mais lista duplamente ligada, as duas no ``OrderedDict``: a tabela
acha a chave em O(1), e a lista guarda a ordem de uso. Ler ou gravar move a chave
para o fim; quando a capacidade estoura, sai a do começo, a usada há mais tempo.

Uso: vetores de texto já calculados (``domain.memory.embedding.CachedEmbedder``).
Pedidos repetidos ("que horas são?") não passam de novo pelo modelo de embedding.

===============  ======
Operação         Custo
===============  ======
``get``          O(1)
``put``          O(1)
``in``           O(1)
===============  ======
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class LRUCache[K: Hashable, V]:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            msg = "a capacidade do cache precisa ser pelo menos 1"
            raise ValueError(msg)
        self.capacity = capacity
        self.stats = CacheStats()
        self._items: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        """O valor (e a chave passa a ser a mais recente), ou ``None``."""
        if key not in self._items:
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key: K, value: V) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)
            self.stats.evictions += 1

    def discard(self, key: K) -> None:
        self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()

    def __contains__(self, key: object) -> bool:
        return key in self._items  # não conta como uso

    def __len__(self) -> int:
        return len(self._items)
