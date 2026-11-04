"""Normalização de texto em português, usada pelo Tier 0 e pela checagem de ações."""

from __future__ import annotations

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s%]")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação e com espaços simples."""
    lowered = strip_accents(text.casefold())
    return _SPACES.sub(" ", _PUNCTUATION.sub(" ", lowered)).strip()


_UNITS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
_TENS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}


def parse_number(text: str) -> int | None:
    """Converte "35", "trinta e cinco" ou "cem" em inteiro (0 a 100).

    Devolve ``None`` se o texto não for um número reconhecido.
    """
    words = normalize(text).replace("%", " ").replace("por cento", " ").split()
    if not words:
        return None
    if len(words) == 1 and words[0].isdigit():
        return int(words[0])
    if words == ["cem"]:
        return 100
    if len(words) == 1:
        return _UNITS.get(words[0], _TENS.get(words[0]))
    if len(words) == 3 and words[1] == "e" and words[0] in _TENS and words[2] in _UNITS:
        unit = _UNITS[words[2]]
        return _TENS[words[0]] + unit if 0 < unit < 10 else None
    return None
