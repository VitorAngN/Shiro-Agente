"""Trie de palavras-chave com casamento mais longo, para achar termos num texto.

Cada nó é um caractere; o caminho da raiz até um nó marcado soletra uma chave.
Uma chave pode ser:

* exata (``"pdf"``, ``"quem ganhou"``): precisa terminar numa fronteira de palavra;
* um radical (``"lembr*"``): casa com qualquer palavra que comece assim
  ("lembra", "lembrete", "lembrar").

Em cada início de palavra do texto, a busca desce pela trie e fica com a chave
**mais longa** que casou. Isso permite exceções: com ``"memoria*" -> memória`` e
``"memoria ram" -> None``, "quanta memória RAM" não traz as ferramentas de
memória, porque "memoria ram" é mais longa e vale mais.

Custo: inserir é O(tamanho da chave); procurar é O(n·L), com n o tamanho do texto
e L a chave mais longa, sem depender de quantas chaves existem. Uma lista de
expressões regulares testaria cada uma em cada posição.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_SPACE = " "


class _Node[V]:
    """Um caractere da trie. ``__slots__``: milhares de nós sem um ``__dict__`` cada."""

    __slots__ = ("children", "exact", "stem")

    def __init__(self) -> None:
        self.children: dict[str, _Node[V]] = {}
        # A tupla distingue "nenhuma chave termina aqui" (None) de "termina, valor None".
        self.exact: tuple[V | None] | None = None
        self.stem: tuple[V | None] | None = None  # radical ("lembr*") que termina aqui


@dataclass(frozen=True)
class Match[V]:
    start: int
    end: int
    key: str
    value: V | None


class KeywordTrie[V]:
    """Mapa de chaves (exatas ou radicais com ``*``) para valores; ``None`` é uma exceção."""

    def __init__(self, entries: Iterable[tuple[str, V | None]] = ()) -> None:
        self._root: _Node[V] = _Node()
        self._size = 0
        for key, value in entries:
            self.add(key, value)

    def add(self, key: str, value: V | None) -> None:
        """Acrescenta uma chave. O texto e as chaves já devem vir normalizados (minúsculas)."""
        is_stem = key.endswith("*")
        word = " ".join(key.removesuffix("*").split())
        if not word:
            msg = "chave vazia na trie"
            raise ValueError(msg)
        node = self._root
        for char in word:
            node = node.children.setdefault(char, _Node())
        if is_stem:
            if node.stem is None:
                self._size += 1
            node.stem = (value,)
        else:
            if node.exact is None:
                self._size += 1
            node.exact = (value,)

    def longest_at(self, text: str, start: int) -> Match[V] | None:
        """A chave mais longa que casa a partir de ``start`` (um início de palavra)."""
        node = self._root
        best: Match[V] | None = None
        position = start
        while position < len(text) and (child := node.children.get(text[position])):
            node = child
            position += 1
            at_boundary = position == len(text) or text[position] == _SPACE
            if node.exact is not None and at_boundary:
                best = Match(start, position, text[start:position], node.exact[0])
            if node.stem is not None:
                end = text.find(_SPACE, position)
                end = len(text) if end == -1 else end
                if best is None or end > best.end:
                    best = Match(start, end, text[start:position] + "*", node.stem[0])
        return best

    def scan(self, text: str) -> list[Match[V]]:
        """Todas as chaves no texto, da esquerda para a direita, sem sobreposição."""
        found: list[Match[V]] = []
        position = 0
        while position < len(text):
            if text[position] == _SPACE:
                position += 1
                continue
            match = self.longest_at(text, position)
            if match is None:
                skip = text.find(_SPACE, position)
                position = len(text) if skip == -1 else skip + 1
                continue
            found.append(match)
            position = match.end
        return found

    def values_in(self, text: str) -> set[V]:
        """Os valores das chaves encontradas, ignorando as exceções (``None``)."""
        return {m.value for m in self.scan(text) if m.value is not None}

    def __len__(self) -> int:
        return self._size
