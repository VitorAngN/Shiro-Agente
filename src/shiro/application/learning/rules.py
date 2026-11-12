"""Tier 0 do aprendizado: "quando eu disser X, faça Y", "desaprende X", "o que você aprendeu?".

Estas regras olham o texto como foi falado, antes de as lições serem aplicadas:
senão "desaprende stim" viraria "desaprende steam".
"""

from __future__ import annotations

import re

from shiro.domain.text import strip_accents

type Calls = list[tuple[str, dict[str, object]]]

_CALL = r"^(?:(?:ei|ok|oi)[, ]+)?(?:shiro[, ]+)?"
_SAID = r"(?:quando|sempre que|se) eu (?:disser|falar|pedir|mandar)"
_QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb"
# Com vírgula (como o Whisper escreve) ou com uma palavra que separa as duas partes.
_WHEN = re.compile(
    rf"{_CALL}{_SAID}\s+(?P<trigger>.+?)\s*"
    r"(?:,\s*(?:entao\s+)?(?:voce\s+)?(?:e\s+(?:pra|para)\s+)?"
    r"|\s+entao\s+(?:voce\s+)?|\s+e\s+(?:pra|para)\s+|\s+voce\s+(?:deve\s+)?"
    r"|\s+quero\s+que\s+(?:voce\s+)?|\s+significa\s+|\s+quer\s+dizer\s+)"
    r"(?P<meaning>.+)$"
)
_MEANS = re.compile(
    rf"{_CALL}(?:aprend[ae]|entend[ae]|saiba)\s+que\s+(?P<trigger>.+?)\s*"
    r"(?:,\s*|\s+)(?:significa|quer\s+dizer|e\s+o\s+mesmo\s+que|e\s+a\s+mesma\s+coisa\s+que|e)\s+"
    r"(?P<meaning>.+)$"
)
_FORGET = re.compile(
    rf"{_CALL}(?:desaprend[ae]|(?:esquec[ae]|apag[ae]|remov[ae])\s+(?:o\s+comando|a\s+expressao"
    r"|o\s+que\s+eu\s+(?:te\s+)?ensinei\s+sobre))\s+(?P<trigger>.+)$"
)
_LIST = re.compile(
    rf"{_CALL}(?:o\s+que\s+(?:voce\s+)?(?:ja\s+)?aprendeu|o\s+que\s+eu\s+(?:ja\s+)?(?:te\s+)?ensinei"
    r"|quais\s+(?:comandos|expressoes)\s+(?:voce\s+)?(?:ja\s+)?(?:aprendeu|sabe))$"
)


def _spoken(text: str) -> str:
    """Minúsculas e sem acento, mas com a vírgula: ela separa a expressão do significado."""
    lowered = strip_accents(text.casefold()).strip()
    return re.sub(r"\s+", " ", lowered).rstrip(".!?… ")


def _unquote(text: str) -> str:
    return text.strip().strip(_QUOTES).strip(" ,")


class LearningRules:
    def __call__(self, text: str) -> Calls | None:
        spoken = _spoken(text)
        if _LIST.match(spoken):
            return [("list_lessons", {})]
        if match := _FORGET.match(spoken):
            return [("forget_lesson", {"trigger": _unquote(match["trigger"])})]
        if match := (_WHEN.match(spoken) or _MEANS.match(spoken)):
            trigger, meaning = _unquote(match["trigger"]), _unquote(match["meaning"])
            if trigger and meaning:
                return [("learn_lesson", {"trigger": trigger, "meaning": meaning})]
        return None
