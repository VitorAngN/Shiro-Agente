"""O que o usuário ensinou: "quando eu disser X, faça Y" (ADR-0023).

Uma lição troca um jeito de falar (``trigger``) pelo que ele quer dizer
(``meaning``). A troca acontece antes do roteador, então o significado passa
pelas mesmas regras, pela política e pela confirmação de qualquer pedido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MAX_TRIGGER_WORDS = 6
MAX_MEANING_CHARS = 200
MAX_LESSONS = 300


@dataclass(frozen=True)
class Lesson:
    trigger: str  # normalizado: minúsculas, sem acento nem pontuação
    meaning: str  # como o usuário falou
    created_at: datetime


class LessonStore(Protocol):
    async def all(self) -> list[Lesson]: ...

    async def put(self, lesson: Lesson) -> None:
        """Grava ou substitui a lição desse ``trigger``."""
        ...

    async def remove(self, trigger: str) -> bool: ...
