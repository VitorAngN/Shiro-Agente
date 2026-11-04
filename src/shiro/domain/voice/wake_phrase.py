"""Reconhecer o chamado ("Ei, Shiro") no texto transcrito, do jeito que o Whisper escreve."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from shiro.domain.text import normalize

# Como o Whisper escreve o chamado: "Ei, Shiro", "Aishiro", "Aiciro", "Eishiro", "A. Shiro".
_NAME = r"(?:shiro|xiro|chiro|shiru|xiru|shirou|shirow)"


_GREETING = r"(?:ei|ai|hei|hey|oi|ok|okay)"


_WAKE = re.compile(
    r"^(?:(?:hum|hm|ah|eh|ahn)\s*,?\s*)?"
    rf"(?:(?:{_GREETING}|e|a)(?:{_NAME}|ciro|ciru|chiru)"  # grudado: "aishiro", "aiciru"
    rf"|(?:{_GREETING}\s*,?\s*)?{_NAME}"  # "ei, shiro" ou só "shiro"
    # "e shiro," / "a shiro.": artigo só vale como chamado (vírgula ou fim depois do nome),
    # para "a Shiro é legal" numa conversa não acordá-la.
    rf"|(?:e|a)\s*,?\s*{_NAME}(?=\s*(?:,|$)))"
    r"\b\s*,?\s*(?P<rest>.*)$"
)


def _plain(text: str) -> str:
    """Minúsculas sem acento; pontuação de fim vira vírgula, para marcar o vocativo."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    plain = re.sub(r"[.!?;:…]+", ",", plain)
    plain = re.sub(r"[^a-z0-9, ]", " ", plain)
    plain = re.sub(r"\s*,\s*", ", ", plain)
    return re.sub(r"\s+", " ", plain).strip(" ,")


def wake_match(text: str, phrases: Sequence[str]) -> str | None:
    """Resto do pedido depois da palavra de ativação, ``""`` se só chamou, ou ``None``.

    >>> wake_match("Ei, Shiro, abre o Spotify.", ["ei shiro", "shiro"])
    'abre o spotify'
    """
    plain = _plain(text)
    if match := _WAKE.match(plain):
        return normalize(match["rest"].replace(",", " ")).strip()
    # Frases configuradas pelo usuário (outro nome, outra saudação).
    flat = normalize(plain.replace(",", " "))
    for phrase in sorted((normalize(p) for p in phrases), key=len, reverse=True):
        if flat == phrase:
            return ""
        if flat.startswith(phrase + " "):
            return flat[len(phrase) + 1 :].strip()
    return None


def strip_wake(text: str, phrases: Sequence[str]) -> str:
    """Tira a palavra de ativação do começo, preservando acentos e maiúsculas do resto."""
    words = text.split()
    for size in range(min(len(words), 4), 0, -1):
        if wake_match(" ".join(words[:size]), phrases) == "":
            return " ".join(words[size:]).lstrip(",.!? ").strip()
    return text.strip()
