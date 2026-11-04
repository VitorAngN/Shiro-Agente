"""Embedding por radicais e o cache LRU que evita recalcular vetores."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from shiro.domain.memory.embedding import CachedEmbedder, HashingEmbedder, Vectors, shares_stem


class CountingEmbedder:
    def __init__(self) -> None:
        self.inner = HashingEmbedder(64)
        self.batches: list[list[str]] = []

    @property
    def name(self) -> str:
        return "contador"

    @property
    def relevant_score(self) -> float:
        return 0.4

    @property
    def match_score(self) -> float:
        return 0.5

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors:
        self.batches.append(list(texts))
        return await self.inner.embed(texts, query=query)


async def test_cache_skips_texts_already_embedded() -> None:
    counting = CountingEmbedder()
    cached = CachedEmbedder(counting, capacity=8)
    first = await cached.embed(["que horas são", "abre o spotify"], query=True)
    again = await cached.embed(["abre o spotify", "volume 20", "que horas são"], query=True)
    assert counting.batches == [["que horas são", "abre o spotify"], ["volume 20"]]
    assert np.allclose(again[0], first[1]) and np.allclose(again[2], first[0])
    assert cached.cache.stats.hits == 2 and cached.name == "contador"
    assert cached.relevant_score == 0.4 and cached.match_score == 0.5
    await cached.embed(["que horas são"], query=False)  # fato e pergunta são chaves diferentes
    assert counting.batches[-1] == ["que horas são"]
    assert (await cached.embed([], query=True)).shape[0] == 0


async def test_cached_vectors_are_copies() -> None:
    cached = CachedEmbedder(CountingEmbedder())
    vector = (await cached.embed(["café"], query=True))[0]
    vector[:] = 0
    assert np.linalg.norm((await cached.embed(["café"], query=True))[0]) > 0.99


def test_shares_stem() -> None:
    assert shares_stem("esquece o café", "gosto de café coado")
    assert not shares_stem("esquece a Ana", "gosto de café")
