"""Habilidades: criar, achar pelo que foi dito, listar e esquecer (ADR-0025)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from shiro.domain.models import ToolResult
from shiro.domain.ports import Clock
from shiro.domain.skills.models import (
    MAX_NAME_WORDS,
    MAX_SKILLS,
    MAX_STEPS,
    SLOT,
    Skill,
    SkillStep,
    SkillStore,
)
from shiro.domain.text import normalize

type Calls = list[tuple[str, dict[str, object]]]
type StepCheck = Callable[[str, dict[str, Any]], str | None]
"""Devolve o problema do passo (ferramenta inexistente, argumento errado) ou ``None``."""
type StepWords = Callable[[str, dict[str, Any]], str]
"""Frase curta de um passo, para mostrar na confirmação ("abrir o Spotify")."""

_CALL = re.compile(r"^(?:(?:ei|ok|hey|oi)\s+)?(?:shiro\s+)?")
_RUN = re.compile(
    r"^(?:(?:faz|faca|fazer|executa|execute|roda|rode|ativa|ative|usa|use)\s+)?"
    r"(?:(?:a|o)\s+)?(?:habilidade\s+)?"
)
_POLITE = re.compile(r"\s+(?:por favor|pf|pfv|pra mim)$")


def _key(name: str) -> str:
    """Nome normalizado, preservando o ``{x}`` do fim."""
    slot = name.strip().endswith(SLOT)
    plain = normalize(name.strip().removesuffix(SLOT))
    return f"{plain} {SLOT}" if slot else plain


class Skills:
    def __init__(self, store: SkillStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        self._skills: dict[str, Skill] = {}

    async def load(self) -> None:
        self._skills = {skill.name: skill for skill in await self._store.all()}

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    # ------------------------------------------------------------ criar

    def parse(self, name: str, description: str, steps_json: str, check: StepCheck) -> Skill | str:
        """A habilidade pronta para gravar, ou o motivo de não dar."""
        key = _key(name)
        if not key.replace(SLOT, "").strip():
            return "Faltou o nome da habilidade (o que você vai falar para usar)."
        if len(key.split()) > MAX_NAME_WORDS:
            return f"O nome precisa ter até {MAX_NAME_WORDS} palavras."
        try:
            raw = json.loads(steps_json)
        except json.JSONDecodeError:
            return 'Os passos precisam ser JSON: [{"tool": "...", "args": {...}}].'
        if not isinstance(raw, list) or not raw:
            return "A habilidade precisa de pelo menos um passo."
        if len(raw) > MAX_STEPS:  # pyright: ignore[reportUnknownArgumentType]
            return f"No máximo {MAX_STEPS} passos por habilidade."
        steps: list[SkillStep] = []
        for index, item in enumerate(raw, start=1):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            if not isinstance(item, dict) or not isinstance(item.get("tool"), str):  # pyright: ignore[reportUnknownMemberType]
                return f'O passo {index} precisa de "tool".'
            args = item.get("args") or {}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if not isinstance(args, dict):
                return f"Os argumentos do passo {index} precisam ser um objeto."
            step = SkillStep(str(item["tool"]), dict(args))  # pyright: ignore[reportUnknownArgumentType]
            problem = check(step.tool, step.filled("teste"))
            if problem:
                return f"Passo {index} ({step.tool}): {problem}"
            steps.append(step)
        uses_slot = any(SLOT in json.dumps(s.args, ensure_ascii=False) for s in steps)
        if uses_slot and not key.endswith(SLOT):
            return "Os passos usam {x}, então o nome precisa terminar com {x}."
        if key not in self._skills and len(self._skills) >= MAX_SKILLS:
            return "Já tenho habilidades demais; peça para eu esquecer alguma."
        return Skill(key, " ".join(description.split())[:200], tuple(steps), self._clock.now())

    async def save(self, skill: Skill) -> ToolResult:
        await self._store.put(skill)
        self._skills[skill.name] = skill
        spoken = skill.name.replace(SLOT, "e o que você quiser")
        message = f"Aprendi a habilidade “{skill.name}”. É só falar “{spoken}”."
        return ToolResult(ok=True, content=message, say=message)

    # ------------------------------------------------------------ usar

    def match(self, text: str) -> Calls | None:
        """Os passos da habilidade que o pedido chama, já com o ``{x}`` trocado."""
        if not self._skills:
            return None
        command = _POLITE.sub("", _CALL.sub("", normalize(text))).strip()
        bare = _RUN.sub("", command, count=1).strip()
        for spoken in dict.fromkeys((command, bare)):
            exact = self._skills.get(spoken)
            if exact is not None and not exact.has_slot:
                return [(step.tool, dict(step.args)) for step in exact.steps]
        best: tuple[int, Skill, str] | None = None
        for skill in self._skills.values():
            if not skill.has_slot:
                continue
            for spoken in (command, bare):
                if spoken.startswith(skill.prefix + " ") and len(skill.prefix) > len(
                    best[1].prefix if best else ""
                ):
                    rest = _original_rest(text, len(skill.prefix.split()) + _lead(spoken, command))
                    best = (len(skill.prefix), skill, rest)
        if best is None or not best[2]:
            return None
        return [(step.tool, step.filled(best[2])) for step in best[1].steps]

    # ------------------------------------------------------------ listar e esquecer

    async def forget(self, name: str) -> ToolResult:
        key = _key(name)
        found = key if key in self._skills else _closest_key(key, self._skills)
        if found is None:
            return ToolResult.failure(f"Não tenho nenhuma habilidade “{name}”.")
        await self._store.remove(found)
        del self._skills[found]
        return ToolResult(
            ok=True, content=f"Esqueci “{found}”.", say=f"Esqueci a habilidade {found}."
        )

    def describe(self, words: StepWords) -> ToolResult:
        if not self._skills:
            return ToolResult(
                ok=True, content="Ainda não tenho habilidades.", say="Ainda não tenho habilidades."
            )
        lines = [
            f"- {s.name}: " + "; ".join(words(step.tool, step.args) for step in s.steps)
            for s in self._skills.values()
        ]
        names = ", ".join(s.name.replace(SLOT, "...") for s in self._skills.values())
        return ToolResult(ok=True, content="\n".join(lines), say=f"Sei fazer: {names}.")


def _lead(spoken: str, command: str) -> int:
    """Quantas palavras do começo ("faz a habilidade") ficaram de fora em ``spoken``."""
    return len(command.split()) - len(spoken.split())


def _original_rest(text: str, skip_words: int) -> str:
    """O resto da frase como foi dito (com acentos), depois das palavras do nome."""
    words = _CALL_WORDS.sub("", text.strip()).split()
    return " ".join(words[skip_words:]).strip(" .,;!?")


_CALL_WORDS = re.compile(r"^(?:(?:ei|ok|hey|oi)[,\s]+)?(?:shiro[,\s]+)?", re.IGNORECASE)


def _closest_key(key: str, skills: dict[str, Skill]) -> str | None:
    plain = key.replace(SLOT, "").strip()
    for name in skills:
        if name.replace(SLOT, "").strip() == plain:
            return name
    return None


def steps_preview(skill: Skill, words: StepWords) -> str:
    return "; ".join(f"{i}) {words(s.tool, s.args)}" for i, s in enumerate(skill.steps, start=1))
