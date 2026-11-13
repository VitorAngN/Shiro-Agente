"""Normalização de texto em português, usada pelo Tier 0 e pela checagem de ações."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

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


# ------------------------------------------------------------------ som das palavras

_SOUND_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), replacement)
    for pattern, replacement in (
        (r"^[ei](?=s[bcdfgklmnpqrtvz])", ""),  # "esteam", "istim" → "steam", "stim"
        (r"chr", "kr"),  # "chrome" se fala "crome"
        (r"ch|sh", "x"),
        (r"ph", "f"),
        (r"th", "t"),
        (r"ck|qu|c(?=[aou])|c$", "k"),
        (r"c(?=[eiy])|ç|z", "s"),
        (r"c", "k"),
        (r"w", "u"),
        (r"y", "i"),
        (r"ee|ea|ie", "i"),  # "steam" → "stim"
        (r"oo|ou", "u"),
        (r"h", ""),
        (r"m(?=[^aeiou]|$)", "n"),  # "stim" e "stin" soam igual
        (r"(.)\1+", r"\1"),
        (r"(?<=..)[aeiou]+$", ""),  # vogal final some: "crome", "cromo" → "kron"
    )
)


def sound_key(text: str) -> str:
    """Chave de pronúncia aproximada, para nomes estrangeiros ditos em português.

    >>> sound_key("Chrome") == sound_key("crome")
    True
    >>> sound_key("Steam") == sound_key("istim")
    True
    """
    key = re.sub(r"[^a-z]", "", strip_accents(text.casefold()))
    for pattern, replacement in _SOUND_RULES:
        key = pattern.sub(replacement, key)
    return key


def similarity(a: str, b: str) -> float:
    """1 menos a distância de edição relativa (Levenshtein): 1.0 é igual, 0.0 nada a ver."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, start=1):
        current = [i]
        for j, right in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return 1.0 - previous[-1] / max(len(a), len(b))


def closest_name(spoken: str, names: Sequence[str], *, minimum: float = 0.78) -> str | None:
    """O nome da lista que mais se parece com o que foi dito ("cloud" → "Claude").

    Igual vence; depois, o dito como palavra inteira dentro do nome ("chrome" em
    "Google Chrome"); depois, parecido na escrita ou na pronúncia. ``None`` se nada
    passar de ``minimum`` ou se dois nomes diferentes empatarem.
    """
    wanted = normalize(spoken)
    if len(wanted) < 2:
        return None
    wanted_sound = sound_key(wanted)
    scored: list[tuple[float, int, str]] = []
    for name in names:
        plain = normalize(name)
        if not plain:
            continue
        if plain == wanted:
            score = 1.0
        elif re.search(rf"(?:^| ){re.escape(wanted)}(?: |$)", plain):
            score = 0.92
        else:
            words = plain.split()
            # o nome inteiro e o começo valem mais que uma palavra solta do meio
            candidates = [(plain, 1.0), (words[0], 0.97), (" ".join(words[:2]), 0.97)]
            candidates += [(word, 0.9) for word in words[1:]]
            score = max(similarity(wanted, c) * w for c, w in candidates)
            if len(wanted_sound) >= 3:
                score = max(
                    score,
                    *(similarity(wanted_sound, sound_key(c)) * w * 0.97 for c, w in candidates),
                )
        scored.append((score, -len(plain), name))
    if not scored:
        return None
    scored.sort(reverse=True)
    best = scored[0]
    if best[0] < minimum:
        return None
    rival = next((s for s in scored[1:] if normalize(s[2]) != normalize(best[2])), None)
    if rival is not None and best[0] < 1.0 and best[0] - rival[0] < 0.03 and rival[0] < 0.92:
        return None
    return best[2]
