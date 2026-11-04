"""Vetores de texto para achar memórias por semelhança (RF-42).

* ``Embedder``: a porta. Os vetores saem normalizados: semelhança é o produto escalar.
* ``HashingEmbedder``: reserva sem download, por palavras e radicais. Acha
  "café" em "gosto de café", mas não sinônimos.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from typing import Protocol

import numpy as np
import numpy.typing as npt

from shiro.domain.text import normalize
from shiro.structures.lru import LRUCache

type Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Identifica o modelo; vetores de outro modelo são recalculados."""
        ...

    @property
    def relevant_score(self) -> float:
        """Semelhança mínima para uma memória entrar no contexto."""
        ...

    @property
    def match_score(self) -> float:
        """Semelhança mínima para "esquece X" apagar uma memória."""
        ...

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors: ...


_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "e", "que", "eu",
    "meu", "minha", "meus", "minhas", "pra", "para", "pro", "no", "na", "em", "com", "por",
    "se", "me", "mim", "voce", "qual", "quais", "sou", "tenho", "isso",
}  # fmt: skip


def shares_stem(a: str, b: str) -> bool:
    """Têm pelo menos um radical em comum? Trava de segurança para apagar memórias."""
    return bool(set(_stems(a)) & set(_stems(b)))


def _stems(text: str) -> list[str]:
    words = [w for w in normalize(text).replace(",", " ").replace(".", " ").split() if w]
    return [w[:5] for w in words if w not in _STOPWORDS and len(w) > 1]


class HashingEmbedder:
    """Saco de radicais com hash: sem modelo, sem download, determinístico."""

    def __init__(self, dimensions: int = 512) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return f"hash-v1-{self._dimensions}"

    @property
    def relevant_score(self) -> float:
        return 0.3  # uma palavra em comum numa frase curta (~0,33) já conta

    @property
    def match_score(self) -> float:
        return 0.5

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors:
        vectors = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for stem in _stems(text):
                vectors[row, zlib.crc32(stem.encode()) % self._dimensions] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)


class CachedEmbedder:
    """Decorador de ``Embedder`` com cache LRU: o mesmo texto não passa duas vezes pelo modelo.

    Cada turno calcula o vetor da fala para buscar memórias; pedidos repetidos
    ("que horas são?", "abre o spotify") saem do cache. Os textos que faltam vão
    juntos ao modelo, numa chamada só.
    """

    def __init__(self, inner: Embedder, capacity: int = 256) -> None:
        self._inner = inner
        self.cache: LRUCache[tuple[str, bool], Vectors] = LRUCache(capacity)

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def relevant_score(self) -> float:
        return self._inner.relevant_score

    @property
    def match_score(self) -> float:
        return self._inner.match_score

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors:
        found: dict[int, Vectors] = {}
        missing: list[int] = []
        for position, text in enumerate(texts):
            cached = self.cache.get((text, query))
            if cached is None:
                missing.append(position)
            else:
                found[position] = cached
        if missing:
            fresh = await self._inner.embed([texts[i] for i in missing], query=query)
            for position, vector in zip(missing, fresh, strict=True):
                found[position] = vector.copy()
                self.cache.put((texts[position], query), found[position])
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        return np.stack([found[i] for i in range(len(texts))]).astype(np.float32)
