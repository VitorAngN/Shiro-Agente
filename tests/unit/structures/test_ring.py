"""Buffer circular: capacidade fixa, sobrescreve o mais antigo, índices e iteração."""

from __future__ import annotations

import pytest

from shiro.structures.ring import RingBuffer


def test_keeps_only_the_last_items() -> None:
    ring: RingBuffer[int] = RingBuffer(3)
    assert not ring and ring.append(1) is None and ring.append(2) is None
    assert ring.to_list() == [1, 2] and not ring.full
    ring.append(3)
    assert ring.full and ring.append(4) == 1  # o mais antigo sai
    assert ring.append(5) == 2
    assert ring.to_list() == [3, 4, 5] and len(ring) == 3
    assert ring[0] == 3 and ring[-1] == 5 and ring[1] == 4
    with pytest.raises(IndexError):
        _ = ring[3]
    assert repr(ring) == "RingBuffer([3, 4, 5], capacity=3)"


def test_clear_and_reuse() -> None:
    ring: RingBuffer[str] = RingBuffer(2)
    for item in "abcde":
        ring.append(item)
    ring.clear()
    assert len(ring) == 0 and ring.to_list() == []
    ring.append("z")
    assert ring.to_list() == ["z"] and ring.capacity == 2


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacidade"):
        RingBuffer(0)
