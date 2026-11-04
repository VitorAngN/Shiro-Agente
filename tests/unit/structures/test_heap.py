"""Fila de prioridade: ordem, estabilidade, substituição e remoção preguiçosa."""

from __future__ import annotations

import heapq
import random

import pytest

from shiro.structures.heap import PriorityQueue


def test_pops_in_priority_order_and_ties_by_arrival() -> None:
    queue: PriorityQueue[int, str] = PriorityQueue()
    for priority, key in [(5, "e"), (1, "a"), (3, "c"), (1, "b"), (4, "d")]:
        queue.push(priority, key)
    top = queue.peek()
    assert len(queue) == 5 and top is not None and top.key == "a"
    assert [queue.pop().key for _ in range(5)] == ["a", "b", "c", "d", "e"]
    assert not queue and queue.peek() is None
    with pytest.raises(IndexError):
        queue.pop()


def test_push_replaces_and_discard_is_lazy() -> None:
    queue: PriorityQueue[int, str] = PriorityQueue()
    queue.push(10, "x")
    queue.push(20, "y")
    queue.push(1, "y")  # a mesma chave com prioridade nova
    assert len(queue) == 2 and queue.priority_of("y") == 1
    assert queue.discard("x") and not queue.discard("x") and "x" not in queue
    assert queue.pop().key == "y"
    assert len(queue) == 0


def test_pop_until_takes_everything_due() -> None:
    queue = PriorityQueue.of([(30, "c"), (10, "a"), (20, "b"), (40, "d")])
    assert [item.key for item in queue.pop_until(25)] == ["a", "b"]
    assert [item.key for item in queue.pop_until(25)] == []
    assert len(queue) == 2


def test_of_keeps_the_last_duplicate() -> None:
    queue = PriorityQueue.of([(5, "a"), (1, "b"), (0, "a")])
    assert [queue.pop().key for _ in range(2)] == ["a", "b"]


def test_matches_heapq_on_random_operations() -> None:
    """Referência: o heapq com remoções feitas na mão."""
    rng = random.Random(7)  # noqa: S311 - sorteio de teste, não de segurança
    queue: PriorityQueue[int, int] = PriorityQueue()
    reference: dict[int, int] = {}
    for _ in range(2000):
        op = rng.random()
        if op < 0.5:
            key, priority = rng.randrange(200), rng.randrange(1000)
            queue.push(priority, key)
            reference[key] = priority
        elif op < 0.7 and reference:
            key = rng.choice(list(reference))
            queue.discard(key)
            del reference[key]
        elif reference:
            item = queue.pop()
            expected = heapq.nsmallest(1, reference.values())[0]
            assert item.priority == expected
            del reference[item.key]
        assert len(queue) == len(reference)
    # As marcas de removido não acumulam sem limite.
    assert len(queue._heap) <= max(64, 2 * len(reference)) + 1  # pyright: ignore[reportPrivateUsage]
