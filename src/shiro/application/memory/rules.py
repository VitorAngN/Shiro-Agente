"""Tier 0 da memória: "lembra que…", "esquece…", "o que você sabe sobre mim?".

"Me lembra de…" é lembrete (``activities.rules``), não memória. E "lembra que
tenho prova amanhã" tem prazo: vai para atividades, não para a memória.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from shiro.domain.activities import dates

type Calls = list[tuple[str, dict[str, object]]]

_REMEMBER = re.compile(
    r"^(?:lembra|lembre|lembre se|guarda|grava|memoriza|salva na memoria|anota na memoria)"
    r"\s+(?:que|isso|disso|isto)\s+(?P<fact>.+)$"
)
_FORGET_ALL = re.compile(
    r"^(?:esquece|esqueca|apaga|limpa)\s+(?:tudo|todas as memorias|a memoria)$"
)
_FORGET = re.compile(
    r"^(?:pode\s+)?(?:esquece|esqueca|esquecer)\s+"
    r"(?:que\s+|o que eu (?:te )?(?:falei|disse) sobre\s+|sobre\s+|da\s+|do\s+)?(?P<q>.+)$"
)
# "de manhã" sozinho é hábito ("prefiro reuniões de manhã"), não prazo.
_DAY_PART_ONLY = re.compile(r"^(?:(?:a|de|pela|na|no|a)\s+)?(?:manha|tarde|noite)(?:\s+cedo)?$")
_LIST = re.compile(
    r"^(?:o que voce (?:sabe|lembra|guardou) (?:sobre mim|de mim)"
    r"|quais sao (?:as )?suas memorias|o que (?:tem|esta) na (?:sua )?memoria)$"
)


class MemoryRules:
    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now

    def __call__(self, text: str) -> Calls | None:
        tokens = dates.words(text)
        plain = " ".join(p for _, p in tokens)
        plain = re.sub(r"^(?:(?:ei|ok|oi) )?shiro ", "", plain)
        if _LIST.match(plain):
            return [("list_memories", {})]
        if _FORGET_ALL.match(plain):
            return [("forget_all_memories", {})]
        if match := _REMEMBER.match(plain):
            start = len(tokens) - len(match["fact"].split())
            fact = " ".join(t for t, _ in tokens[start:])
            spans = dates.locate(fact, now=self._now())
            if any(not _DAY_PART_ONLY.match(span.plain) for span in spans):
                return None  # tem prazo: é atividade ou lembrete, o modelo decide
            return [("remember_fact", {"text": fact})]
        if (match := _FORGET.match(plain)) and len(match["q"].split()) <= 8:
            start = len(tokens) - len(match["q"].split())
            return [("forget_fact", {"query": " ".join(t for t, _ in tokens[start:])})]
        return None
