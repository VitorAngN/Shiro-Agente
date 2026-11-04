"""Trie de palavras-chave: radicais, frases exatas, casamento mais longo e exceções."""

from __future__ import annotations

import pytest

from shiro.structures.trie import KeywordTrie


def build() -> KeywordTrie[str]:
    return KeywordTrie(
        [
            ("lembr*", "memory"),
            ("memoria*", "memory"),
            ("memoria ram", None),  # exceção
            ("pdf", "files"),
            ("na web", "web"),
            ("quem ganhou", "web"),
        ]
    )


@pytest.mark.parametrize(
    ("text", "groups"),
    [
        ("me lembra de beber agua", {"memory"}),
        ("lembrete", {"memory"}),
        ("quanta memoria ram eu tenho", set()),
        ("limpa a memoria", {"memory"}),
        ("memorias ram", {"memory"}),  # "memorias" não é a frase da exceção
        ("abre o pdf", {"files"}),
        ("abre os pdfs", set()),  # exata: precisa terminar na palavra
        ("procura na web quem ganhou", {"web"}),
        ("na webcam", set()),
        ("", set()),
        ("   ", set()),
    ],
)
def test_values_in(text: str, groups: set[str]) -> None:
    assert build().values_in(text) == groups


def test_scan_reports_positions_without_overlap() -> None:
    matches = build().scan("lembra da memoria ram e do pdf")
    assert [(m.key, m.value) for m in matches] == [
        ("lembr*", "memory"),
        ("memoria ram", None),
        ("pdf", "files"),
    ]
    assert matches[0].start == 0 and matches[0].end == len("lembra")


def test_size_and_errors() -> None:
    trie = build()
    assert len(trie) == 6
    trie.add("pdf", "files")  # repetida: substitui, não cresce
    assert len(trie) == 6
    with pytest.raises(ValueError, match="vazia"):
        trie.add("*", "x")
