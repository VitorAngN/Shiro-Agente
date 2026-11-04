"""Buffer circular de capacidade fixa.

Guarda os últimos ``capacity`` itens num vetor pré-alocado. Um índice ``_head``
aponta para o mais antigo; inserir com o buffer cheio sobrescreve o mais antigo
e avança ``_head`` (aritmética módulo ``capacity``). Nada é copiado nem realocado.

Usos: o áudio de antes do início da fala (pré-roll do ``Endpointer``, ~31
quadros por segundo) e os grupos de ferramentas dos últimos turnos do agente.

==================  ======
Operação            Custo
==================  ======
``append``          O(1)
``[i]`` / ``[-1]``  O(1)
iterar              O(n)
``clear``           O(capacidade)
==================  ======
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast


class RingBuffer[T]:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            msg = "a capacidade do buffer circular precisa ser pelo menos 1"
            raise ValueError(msg)
        self._slots: list[T | None] = [None] * capacity
        self._head = 0  # posição do item mais antigo
        self._size = 0

    @property
    def capacity(self) -> int:
        return len(self._slots)

    @property
    def full(self) -> bool:
        return self._size == len(self._slots)

    def append(self, item: T) -> T | None:
        """Insere no fim. Com o buffer cheio, devolve o item mais antigo, que saiu."""
        capacity = len(self._slots)
        if self._size < capacity:
            self._slots[(self._head + self._size) % capacity] = item
            self._size += 1
            return None
        evicted = self._slots[self._head]
        self._slots[self._head] = item
        self._head = (self._head + 1) % capacity
        return evicted

    def clear(self) -> None:
        self._slots = [None] * len(self._slots)  # solta as referências (áudio ocupa memória)
        self._head = self._size = 0

    def to_list(self) -> list[T]:
        """Do mais antigo para o mais novo."""
        return list(self)

    def __getitem__(self, index: int) -> T:
        if not -self._size <= index < self._size:
            msg = "índice fora do buffer circular"
            raise IndexError(msg)
        position = (self._head + index % self._size) % len(self._slots)
        return cast("T", self._slots[position])  # posições ocupadas sempre têm um item

    def __iter__(self) -> Iterator[T]:
        capacity = len(self._slots)
        for offset in range(self._size):
            yield cast("T", self._slots[(self._head + offset) % capacity])

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def __repr__(self) -> str:
        return f"RingBuffer({self.to_list()!r}, capacity={self.capacity})"
