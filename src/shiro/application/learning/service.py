"""Lições do usuário: aprender, esquecer, listar e aplicar ao que ele fala (ADR-0023)."""

from __future__ import annotations

import re

from shiro.domain.learning.models import (
    MAX_LESSONS,
    MAX_MEANING_CHARS,
    MAX_TRIGGER_WORDS,
    Lesson,
    LessonStore,
)
from shiro.domain.models import ToolResult
from shiro.domain.ports import Clock
from shiro.domain.text import normalize


class Lessons:
    """Guarda as lições em memória (o banco é a cópia durável) e reescreve os pedidos."""

    def __init__(self, store: LessonStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        self._lessons: dict[str, Lesson] = {}
        self._pattern: re.Pattern[str] | None = None

    async def load(self) -> None:
        self._lessons = {lesson.trigger: lesson for lesson in await self._store.all()}
        self._compile()

    def expand(self, text: str) -> str:
        """Troca cada expressão ensinada pelo significado; sem lição aplicável, devolve igual."""
        if self._pattern is None:
            return text
        plain = normalize(text)
        if not self._pattern.search(plain):
            return text
        return self._pattern.sub(lambda m: self._lessons[m.group(0)].meaning, plain)

    async def learn(self, trigger: str, meaning: str) -> ToolResult:
        key = normalize(trigger)
        meaning = " ".join(meaning.split()).strip(" .,;")
        if not key or not meaning:
            return _fail("Faltou dizer a expressão ou o que ela significa.")
        if len(key.split()) > MAX_TRIGGER_WORDS:
            return _fail(f"A expressão precisa ter até {MAX_TRIGGER_WORDS} palavras.")
        if len(meaning) > MAX_MEANING_CHARS:
            return _fail("O significado ficou longo demais; ensine em partes.")
        if re.search(rf"\b{re.escape(key)}\b", normalize(meaning)):
            return _fail("O significado não pode repetir a própria expressão.")
        if key not in self._lessons and len(self._lessons) >= MAX_LESSONS:
            return _fail("Já aprendi o máximo de expressões; peça para eu esquecer alguma.")
        lesson = Lesson(key, meaning, self._clock.now())
        await self._store.put(lesson)
        self._lessons[key] = lesson
        self._compile()
        message = f"Aprendi: quando você disser “{key}”, entendo “{meaning}”."
        return ToolResult(ok=True, content=message, say=message)

    async def forget(self, trigger: str) -> ToolResult:
        key = normalize(trigger)
        if not await self._store.remove(key):
            return _fail(f"Não tenho nada ensinado como “{key}”.")
        self._lessons.pop(key, None)
        self._compile()
        message = f"Esqueci “{key}”."
        return ToolResult(ok=True, content=message, say=message)

    async def list(self) -> ToolResult:
        if not self._lessons:
            message = "Você ainda não me ensinou nenhuma expressão."
            return ToolResult(ok=True, content=message, say=message)
        lines = [f"“{lesson.trigger}” → {lesson.meaning}" for lesson in self.lessons()]
        count = len(lines)
        say = f"Aprendi {count} {'expressão' if count == 1 else 'expressões'}: " + "; ".join(
            lines[:5]
        )
        return ToolResult(ok=True, content="\n".join(lines), say=say)

    def lessons(self) -> list[Lesson]:
        return sorted(self._lessons.values(), key=lambda lesson: lesson.trigger)

    def _compile(self) -> None:
        # As expressões mais longas primeiro: "modo jogo" ganha de "jogo".
        triggers = sorted(self._lessons, key=len, reverse=True)
        joined = "|".join(re.escape(t) for t in triggers)
        self._pattern = re.compile(rf"(?<!\w)(?:{joined})(?!\w)") if triggers else None


def _fail(message: str) -> ToolResult:
    return ToolResult(ok=False, content=message, say=message)
