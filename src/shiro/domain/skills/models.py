"""Habilidades: sequências de ações que a SHIRO monta a pedido do usuário (ADR-0025).

"Quero que você saiba abrir meu modo estudo" vira uma habilidade com nome e passos
(ferramentas que já existem, com argumentos). Ela não escreve código: só junta o
que já sabe fazer. Cada passo roda pela política e pela confirmação de sempre.

Um nome pode terminar com ``{x}``: "toca no spotify {x}" guarda o resto da frase
e troca ``{x}`` nos argumentos dos passos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

SLOT = "{x}"
MAX_STEPS = 12
MAX_SKILLS = 200
MAX_NAME_WORDS = 8


@dataclass(frozen=True)
class SkillStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict[str, Any])

    def filled(self, value: str) -> dict[str, Any]:
        """Os argumentos com ``{x}`` trocado pelo que foi dito."""
        return _fill(self.args, value)


@dataclass(frozen=True)
class Skill:
    name: str  # normalizado; pode terminar com {x}
    description: str
    steps: tuple[SkillStep, ...]
    created_at: datetime

    @property
    def has_slot(self) -> bool:
        return self.name.endswith(SLOT)

    @property
    def prefix(self) -> str:
        return self.name.removesuffix(SLOT).strip()


def _fill(value: Any, text: str) -> Any:
    if isinstance(value, str):
        return value.replace(SLOT, text)
    if isinstance(value, dict):
        return {key: _fill(item, text) for key, item in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_fill(item, text) for item in value]  # pyright: ignore[reportUnknownVariableType]
    return value


class SkillStore(Protocol):
    async def all(self) -> list[Skill]: ...

    async def put(self, skill: Skill) -> None: ...

    async def remove(self, name: str) -> bool: ...
