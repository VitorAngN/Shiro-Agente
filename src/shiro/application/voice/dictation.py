"""Modo ditado: o que o usuário fala vai sendo escrito na janela em uso (ADR-0026).

"Shiro, modo ditado" liga; depois cada frase falada é escrita como foi dita,
com a pontuação falada trocada pelo sinal ("vírgula", "nova linha"). "Parar
ditado" encerra. Aqui fica só o que não depende de microfone nem de teclado.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from shiro.domain.text import normalize

_STOP = re.compile(
    r"^(?:(?:ei|ok|oi)\s+)?(?:shiro\s+)?(?:par[ae]r?|pare|fim|encerr[ae]r?|sai|sair|chega|"
    r"termin[ae]r?|deslig[ae]r?|acab[ae]r?)\s+(?:(?:o|do|de|com o)\s+)?(?:modo\s+)?ditado$"
)
# (como o Whisper escreve a palavra falada, o que entra no lugar)
_SPOKEN: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"[ ,.]*\b(?:{words})\b[,.]?", re.IGNORECASE), sign)
    for words, sign in (
        (r"novo par[aá]grafo", "\n\n"),
        (r"nova linha|pr[oó]xima linha|pula(?:r)? linha|quebra de linha", "\n"),
        (r"ponto e v[ií]rgula", ";"),
        (r"ponto de interroga[cç][aã]o|interroga[cç][aã]o", "?"),
        (r"ponto de exclama[cç][aã]o|exclama[cç][aã]o", "!"),
        (r"dois pontos", ":"),
        (r"ponto final", "."),
        (r"v[ií]rgula", ","),
        (r"abre par[eê]nteses?", " ("),
        (r"fecha par[eê]nteses?", ")"),
        (r"abre chaves?", " {"),
        (r"fecha chaves?", "}"),
        (r"abre colchetes?", " ["),
        (r"fecha colchetes?", "]"),
        (r"abre aspas", ' "'),
        (r"fecha aspas", '"'),
        (r"tabula[cç][aã]o", "\t"),
    )
)


def is_stop(text: str) -> bool:
    return _STOP.match(normalize(text)) is not None


def spoken_punctuation(text: str) -> str:
    """ "oi vírgula tudo bem interrogação" → "oi, tudo bem?" """
    result = text.strip()
    for pattern, sign in _SPOKEN:
        result = pattern.sub(sign, result)
    result = re.sub(r"([(\[{]) +", r"\1", result)  # "( a" → "(a"
    result = re.sub(r"([\n\t]) +", r"\1", result)
    return result.strip(" ")


class Dictation:
    """Pedido de ditado pendente e o jeito de escrever na janela em uso."""

    def __init__(self, write: Callable[[str], Awaitable[None]]) -> None:
        self.write = write
        self.requested = False
