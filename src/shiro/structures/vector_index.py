"""Índice de vetores em memória: os k mais parecidos por produto escalar.

Os vetores ficam lado a lado numa matriz ``n x d`` (``float32``, contígua), e
a chave de cada linha fica numa lista paralela. Com vetores normalizados, o
produto escalar é a semelhança do cosseno. Buscar é um produto matriz-vetor,
O(n·d), e ``argpartition`` escolhe os k melhores em O(n) sem ordenar tudo.

Inserir acrescenta numa lista de pendentes, que só vira matriz na próxima busca,
para não copiar a matriz a cada inserção. Remover troca a linha pela última e
encolhe: O(1), sem buracos.

Uso: a memória de longo prazo (``application.memory.service``). Antes, cada
turno relia todos os fatos e vetores do SQLite.

====================  ===========================
Operação              Custo
====================  ===========================
``add``               O(d) (amortizado)
``remove``            O(d)
``search(k)``         O(n·d + n + k log k)
====================  ===========================
"""

from __future__ import annotations

from collections.abc import Hashable

import numpy as np
import numpy.typing as npt

type Vector = npt.NDArray[np.float32]


class VectorIndex[K: Hashable]:
    def __init__(self, dimensions: int | None = None) -> None:
        """``dimensions=None``: o primeiro vetor inserido define o tamanho."""
        self.dimensions = dimensions
        self._matrix: Vector = np.empty((0, dimensions or 0), dtype=np.float32)
        self._keys: list[K] = []
        self._row: dict[K, int] = {}
        self._pending: list[Vector] = []

    def add(self, key: K, vector: Vector) -> None:
        """Insere ou substitui o vetor da chave."""
        flat = np.asarray(vector, dtype=np.float32).reshape(-1)
        if self.dimensions is None:
            self.dimensions = flat.shape[0]
            self._matrix = np.empty((0, self.dimensions), dtype=np.float32)
        if flat.shape != (self.dimensions,):
            msg = f"o índice guarda vetores de {self.dimensions} dimensões, veio {flat.shape}"
            raise ValueError(msg)
        if key in self._row:
            self._flush()
            self._matrix[self._row[key]] = flat
            return
        self._row[key] = len(self._keys)
        self._keys.append(key)
        self._pending.append(flat)

    def remove(self, key: K) -> bool:
        if key not in self._row:
            return False
        self._flush()
        row, last = self._row.pop(key), len(self._keys) - 1
        if row != last:  # a última linha ocupa o lugar da removida
            moved = self._keys[last]
            self._matrix[row] = self._matrix[last]
            self._keys[row] = moved
            self._row[moved] = row
        self._keys.pop()
        self._matrix = self._matrix[:last]
        return True

    def search(self, query: Vector, k: int) -> list[tuple[K, float]]:
        """As ``k`` chaves mais parecidas, da mais para a menos."""
        self._flush()
        if k <= 0 or not self._keys:
            return []
        scores = self._matrix @ np.asarray(query, dtype=np.float32).reshape(-1)
        k = min(k, len(self._keys))
        if k < len(self._keys):
            candidates = np.argpartition(-scores, k - 1)[:k]  # os k melhores, fora de ordem
        else:
            candidates = np.arange(len(self._keys))
        # Ordenação estável: empates saem na ordem de inserção.
        best = candidates[np.argsort(-scores[candidates], kind="stable")]
        return [(self._keys[int(i)], float(scores[i])) for i in best]

    def clear(self) -> None:
        self._matrix = np.empty((0, self.dimensions or 0), dtype=np.float32)
        self._keys.clear()
        self._row.clear()
        self._pending.clear()

    def _flush(self) -> None:
        if self._pending:
            self._matrix = np.vstack([self._matrix, *self._pending]).astype(np.float32)
            self._pending.clear()

    def __contains__(self, key: object) -> bool:
        return key in self._row

    def __len__(self) -> int:
        return len(self._keys)
