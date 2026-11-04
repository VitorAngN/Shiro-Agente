"""Rotinas nomeadas (RF-31, ADR-0018): "modo estudo" fecha o Discord, abre o VS Code...

Cada rotina é uma lista de chamadas de ferramenta no ``shiro.toml``. Ela vira
chamadas do Tier 0: cada passo passa pela política e pela confirmação como se
fosse pedido sozinho, e lotes grandes pedem confirmação (``batch_confirm_threshold``).
Não existe ferramenta "roda a rotina", que executaria passos por fora da política.

Na partida, cada passo é validado contra a ferramenta de verdade. Rotina com
passo inválido é desligada inteira e reportada, nunca executada pela metade.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from shiro.config.settings import RoutineSettings
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolCatalog, ToolContext, ToolSpec
from shiro.domain.text import normalize

type Calls = list[tuple[str, dict[str, object]]]

_VERBS = (
    r"(?:ativa|ativar|liga|ligar|inicia|iniciar|comeca|comecar|entra|entrar|bota|coloca|"
    r"aciona|roda|rodar|executa|executar|vamos|bora)"
)
_TRIGGER = re.compile(
    rf"^(?:{_VERBS}\s+)?(?:(?:no|na|o|a|em|pro|pra)\s+)?(?:(?P<kind>modo|rotina)\s+)?(?:de\s+)?"
    r"(?P<name>.+?)$"
)


@dataclass(frozen=True)
class Routine:
    name: str
    aliases: tuple[str, ...]
    calls: tuple[tuple[str, dict[str, object]], ...]
    description: str = ""


def load_routines(
    configured: Mapping[str, RoutineSettings], tools: ToolCatalog
) -> tuple[dict[str, Routine], list[str]]:
    """Rotinas válidas e a lista de problemas (rotinas desligadas)."""
    valid: dict[str, Routine] = {}
    problems: list[str] = []
    for name, routine in configured.items():
        errors: list[str] = []
        for index, step in enumerate(routine.steps, start=1):
            tool = tools.get(step.tool)
            if tool is None:
                errors.append(f"passo {index}: ferramenta {step.tool} não existe")
                continue
            try:
                tool.spec.args_model.model_validate(step.args)
            except ValidationError as exc:
                errors.append(
                    f"passo {index} ({step.tool}): argumentos inválidos ({exc.error_count()})"
                )
        if errors:
            problems.append(f"rotina {name} desligada: " + "; ".join(errors))
            continue
        valid[normalize(name)] = Routine(
            name=name,
            aliases=tuple(normalize(a) for a in routine.aliases),
            calls=tuple((s.tool, dict(s.args)) for s in routine.steps),
            description=routine.description,
        )
    return valid, problems


class RoutineRules:
    """Tier 0: "modo estudo", "ativa a rotina estudo" ou um apelido exato ("hora de estudar")."""

    def __init__(self, routines: Mapping[str, Routine]) -> None:
        self._routines = routines

    def __call__(self, text: str) -> Calls | None:
        plain = normalize(text).replace(",", " ").replace(".", " ").replace("!", " ")
        plain = re.sub(r"^(?:(?:ei|ok|oi)\s+)?shiro\s+", "", re.sub(r"\s+", " ", plain).strip())
        plain = re.sub(r"\s+(?:por favor|ai|agora)$", "", plain)
        for routine in self._routines.values():
            if plain in routine.aliases:
                return [(tool, dict(args)) for tool, args in routine.calls]
        match = _TRIGGER.match(plain)
        if match is None:
            return None
        name = match["name"]
        explicit = match["kind"] is not None or plain != name
        for key, routine in self._routines.items():
            if (name == key or name in routine.aliases) and explicit:
                return [(tool, dict(args)) for tool, args in routine.calls]
        return None


class NoArgs(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}


class ListRoutinesTool:
    spec = ToolSpec(
        name="list_routines",
        description="Lista as rotinas configuradas (ex.: modo estudo) e o que cada uma faz.",
        args_model=NoArgs,
        risk=RiskLevel.R0,
    )

    def __init__(self, routines: Mapping[str, Routine]) -> None:
        self._routines = routines

    def describe(self, args: BaseModel) -> str:
        return "listar as rotinas"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not self._routines:
            return ToolResult.success(
                "Nenhuma rotina configurada. Elas ficam em [routines] no shiro.toml."
            )
        parts: list[str] = []
        for routine in self._routines.values():
            steps = ", ".join(tool for tool, _ in routine.calls)
            what = routine.description or steps
            parts.append(f'"modo {routine.name}" ({what})')
        return ToolResult.success("Rotinas: " + "; ".join(parts) + ".")
