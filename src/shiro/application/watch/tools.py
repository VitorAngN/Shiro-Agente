"""Ferramentas das esperas: esperar um tempo, vigiar a tela, listar e cancelar (ADR-0027)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shiro.application.watch.service import Steps, Wait, Waits
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Tool, ToolContext, ToolSpec

type StepCheck = Callable[[str, dict[str, Any]], str | None]

_STEPS_HELP = (
    'Passos em JSON, em ordem: [{"tool": "press_keys", "args": {"keys": "k"}}]. '
    "Só ferramentas de ação (click_on, press_keys, type_text, open_url, media_control...)."
)


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AfterArgs(_Args):
    seconds: float = Field(gt=0, le=6 * 3600, description="Daqui a quantos segundos")
    steps_json: str = Field(min_length=2, max_length=4000, description=_STEPS_HELP)
    description: str = Field(min_length=1, max_length=120, description="O que vai fazer, curto")


class WhenSeenArgs(_Args):
    target: str = Field(
        min_length=1,
        max_length=150,
        description="O que precisa aparecer na tela ('botão Aceitar', 'tela de vitória')",
    )
    steps_json: str = Field(min_length=2, max_length=4000, description=_STEPS_HELP)
    description: str = Field(min_length=1, max_length=120, description="O que vai fazer, curto")
    every_s: float = Field(default=6.0, ge=2, le=120, description="De quanto em quanto olhar")
    minutes: float = Field(default=20.0, gt=0, le=120, description="Desiste depois de")


class CancelArgs(_Args):
    wait_id: int | None = Field(default=None, description="Número da espera; vazio = todas")


class NoArgs(_Args):
    pass


def _parse(steps_json: str, check: StepCheck) -> Steps | str:
    try:
        raw: object = json.loads(steps_json)
    except json.JSONDecodeError:
        return "Os passos precisam ser JSON."
    if not isinstance(raw, list) or not raw:
        return "Faltou pelo menos um passo."
    steps: list[tuple[str, dict[str, object]]] = []
    for index, item in enumerate(raw, start=1):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if not isinstance(item, dict) or not isinstance(item.get("tool"), str):  # pyright: ignore[reportUnknownMemberType]
            return f'O passo {index} precisa de "tool".'
        args = item.get("args") or {}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not isinstance(args, dict):
            return f"Os argumentos do passo {index} precisam ser um objeto."
        name = str(item["tool"])  # pyright: ignore[reportUnknownArgumentType]
        problem = check(name, dict(args))  # pyright: ignore[reportUnknownArgumentType]
        if problem:
            return f"Passo {index} ({name}): {problem}"
        steps.append((name, dict(args)))  # pyright: ignore[reportUnknownArgumentType]
    return steps


def _minutes(seconds: float) -> str:
    if seconds < 90:
        return f"{round(seconds)} segundos"
    return f"{round(seconds / 60)} minutos"


class _WaitTool:
    def __init__(self, spec: ToolSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> ToolSpec:
        return self._spec


class AfterTool(_WaitTool):
    def __init__(self, waits: Waits, check: StepCheck) -> None:
        super().__init__(
            ToolSpec(
                name="wait_then",
                description=(
                    "Espera um tempo e depois faz as ações: 'daqui a 5 minutos pausa', 'quando "
                    "o vídeo chegar em 3:00 pausa' (olhe o tempo atual antes e calcule)."
                ),
                args_model=AfterArgs,
                risk=RiskLevel.R1,
                group="control",
            )
        )
        self._waits = waits
        self._check = check

    def problem(self, args: BaseModel) -> str | None:
        parsed = _parse(AfterArgs.model_validate(args.model_dump()).steps_json, self._check)
        return parsed if isinstance(parsed, str) else None

    def describe(self, args: BaseModel) -> str:
        a = AfterArgs.model_validate(args.model_dump())
        return f"daqui a {_minutes(a.seconds)}: {a.description}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        a = AfterArgs.model_validate(args.model_dump())
        steps = _parse(a.steps_json, self._check)
        if isinstance(steps, str):
            return ToolResult.failure(steps)
        made = self._waits.after(a.seconds, steps, a.description)
        if isinstance(made, str):
            return ToolResult.failure(made)
        say = f"Combinado: daqui a {_minutes(a.seconds)}, {a.description}."
        return ToolResult.success(f"Espera {made.id} criada. {say}", say=say)


class WhenSeenTool(_WaitTool):
    def __init__(self, waits: Waits, check: StepCheck) -> None:
        super().__init__(
            ToolSpec(
                name="when_visible",
                description=(
                    "Fica olhando a tela e, quando algo aparecer, faz as ações: 'quando aparecer "
                    "Aceitar no LoL, aceita a partida' (target='botão Aceitar partida', passo "
                    "click_on). Roda em segundo plano."
                ),
                args_model=WhenSeenArgs,
                risk=RiskLevel.R1,
                external=True,
                group="control",
            )
        )
        self._waits = waits
        self._check = check

    def problem(self, args: BaseModel) -> str | None:
        parsed = _parse(WhenSeenArgs.model_validate(args.model_dump()).steps_json, self._check)
        return parsed if isinstance(parsed, str) else None

    def describe(self, args: BaseModel) -> str:
        a = WhenSeenArgs.model_validate(args.model_dump())
        return f"quando aparecer {a.target}: {a.description}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        a = WhenSeenArgs.model_validate(args.model_dump())
        steps = _parse(a.steps_json, self._check)
        if isinstance(steps, str):
            return ToolResult.failure(steps)
        made = self._waits.when_seen(
            a.target, steps, a.description, every_s=a.every_s, timeout_s=a.minutes * 60
        )
        if isinstance(made, str):
            return ToolResult.failure(made)
        say = f"Fico de olho. Quando aparecer {a.target}, {a.description}."
        return ToolResult.success(f"Vigia {made.id} criado. {say}", say=say)


def _line(wait: Wait) -> str:
    kind = f"quando aparecer {wait.target}" if wait.watching else "no tempo marcado"
    return f"{wait.id}) {wait.description} ({kind})"


def wait_tools(waits: Waits, check: StepCheck) -> list[Tool]:
    class ListTool(_WaitTool):
        def describe(self, args: BaseModel) -> str:
            return "listar as esperas"

        async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
            active = waits.active()
            if not active:
                return ToolResult.success("Nenhuma espera ativa.", say="Não estou esperando nada.")
            return ToolResult.success("\n".join(_line(w) for w in active))

    class CancelTool(_WaitTool):
        def describe(self, args: BaseModel) -> str:
            chosen = CancelArgs.model_validate(args.model_dump()).wait_id
            return "cancelar todas as esperas" if chosen is None else f"cancelar a espera {chosen}"

        async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
            count = waits.cancel(CancelArgs.model_validate(args.model_dump()).wait_id)
            if count == 0:
                return ToolResult.failure("Não achei essa espera.")
            return ToolResult.success(f"Cancelei {count}.", say="Cancelado.")

    tools: list[Tool] = [
        AfterTool(waits, check),
        ListTool(
            ToolSpec(
                name="list_waits",
                description="Lista as esperas e vigias ativos.",
                args_model=NoArgs,
                risk=RiskLevel.R0,
                group="control",
            )
        ),
        CancelTool(
            ToolSpec(
                name="cancel_waits",
                description="Cancela uma espera ou vigia (ou todos).",
                args_model=CancelArgs,
                risk=RiskLevel.R1,
                group="control",
            )
        ),
    ]
    if waits.can_watch:
        tools.insert(1, WhenSeenTool(waits, check))
    return tools
