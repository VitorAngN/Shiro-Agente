"""Janela deslizante (limite por minuto) e cache LRU."""

from __future__ import annotations

import pytest

from shiro.structures.lru import LRUCache
from shiro.structures.window import SlidingWindow


def test_sliding_window_counts_only_the_last_span() -> None:
    window = SlidingWindow(60)
    for t in (0, 10, 20, 59):
        window.add(t)
    assert window.count(59) == 4
    assert window.count(60) == 3  # o evento do instante 0 saiu
    assert window.count(130) == 0 and len(window) == 0
    with pytest.raises(ValueError, match="ordem"):
        window.add(10)
        window.add(5)


def test_sliding_window_says_when_the_next_slot_opens() -> None:
    window = SlidingWindow(60)
    for t in (0, 5, 10):
        window.add(t)
    assert window.wait_for_slot(10, limit=4) == 0
    assert window.wait_for_slot(10, limit=3) == 50  # quando o do instante 0 sair
    assert window.wait_for_slot(10, limit=2) == 55
    with pytest.raises(ValueError, match="positiva"):
        SlidingWindow(0)


def test_lru_evicts_the_least_recently_used() -> None:
    cache: LRUCache[str, int] = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # "a" passa a ser o mais recente
    cache.put("c", 3)  # sai "b"
    assert "b" not in cache and cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3 and len(cache) == 2
    assert cache.stats.hits == 3 and cache.stats.misses == 1 and cache.stats.evictions == 1
    assert cache.stats.hit_rate == 0.75
    cache.discard("a")
    cache.clear()
    assert len(cache) == 0
    with pytest.raises(ValueError, match="capacidade"):
        LRUCache(0)
