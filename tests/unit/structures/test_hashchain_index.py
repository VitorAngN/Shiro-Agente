"""Cadeia de hashes (auditoria) e índice de vetores (memória)."""

from __future__ import annotations

import numpy as np
import pytest

from shiro.structures.hashchain import GENESIS, ChainRecord, ChainVerifier, link, verify
from shiro.structures.vector_index import VectorIndex


def chain(n: int) -> list[ChainRecord]:
    records: list[ChainRecord] = []
    prev = GENESIS
    for seq in range(1, n + 1):
        fields = (f"evento {seq}",)
        digest = link(prev, fields)
        records.append(ChainRecord(seq, fields, prev, digest))
        prev = digest
    return records


def test_intact_chain_and_retention_anchor() -> None:
    records = chain(5)
    assert verify(records) is None
    assert verify(records[2:]) is None  # a retenção apagou o começo: o primeiro vira âncora
    assert verify([]) is None


def test_detects_edits_and_removals() -> None:
    records = chain(5)
    edited = [*records[:2], ChainRecord(3, ("outro texto",), records[2].prev_hash, records[2].hash)]
    assert verify(edited + records[3:]) == 3
    assert verify([*records[:2], *records[3:]]) == 4  # o 3 sumiu: o 4 não encaixa mais
    verifier = ChainVerifier()
    assert all(verifier.feed(r) for r in records[:2])
    assert not verifier.feed(edited[2]) and not verifier.feed(records[3])
    assert verifier.broken_at == 3


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_vector_index_top_k() -> None:
    index: VectorIndex[str] = VectorIndex()
    index.add("norte", unit(0, 1))
    index.add("leste", unit(1, 0))
    index.add("nordeste", unit(1, 1))
    assert index.dimensions == 2 and len(index) == 3
    best = index.search(unit(0.2, 1), 2)
    assert [key for key, _ in best] == ["norte", "nordeste"]
    assert best[0][1] > best[1][1]
    assert [key for key, _ in index.search(unit(1, 0), 10)] == ["leste", "nordeste", "norte"]
    assert index.search(unit(1, 0), 0) == []


def test_vector_index_replace_remove_and_shape() -> None:
    index: VectorIndex[int] = VectorIndex(3)
    for key in range(5):
        index.add(key, unit(1, key, 0))
    index.add(2, unit(0, 0, 1))  # substitui
    assert index.search(unit(0, 0, 1), 1)[0][0] == 2
    assert index.remove(0) and not index.remove(0) and 0 not in index
    assert sorted(k for k, _ in index.search(unit(1, 1, 1), 10)) == [1, 2, 3, 4]
    with pytest.raises(ValueError, match="dimensões"):
        index.add(9, np.ones(4, dtype=np.float32))
    index.clear()
    assert len(index) == 0 and index.search(unit(1, 0, 0), 3) == []


def test_vector_index_ties_keep_insertion_order() -> None:
    index: VectorIndex[str] = VectorIndex()
    for key in "abc":
        index.add(key, unit(1, 0))
    assert [k for k, _ in index.search(unit(1, 0), 3)] == ["a", "b", "c"]
