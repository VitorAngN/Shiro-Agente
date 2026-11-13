"""Ferramentas das habilidades: criar (sempre confirma), listar e esquecer (ADR-0025)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from shiro.application.skills.service import Skills, StepCheck, StepWords, steps_preview
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Tool, ToolContext, ToolSpec
from shiro.domain.skills.models import MAX_STEPS, Skill


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateSkillArgs(_Args):
    name: str = Field(
        min_length=1,
        max_length=80,
        description="O que o usuário vai falar para usar ('modo estudo'; com {x} no fim, "
        "o resto da frase entra nos passos: 'toca no spotify {x}')",
    )
    description: str = Field(default="", max_length=200, description="Para que serve")
    steps_json: str = Field(
        min_length=2,
        max_length=4000,
        description='Passos em JSON, em ordem: [{"tool": "open_program", "args": {"name": '
        f'"Spotify"}}}}, ...]. Até {MAX_STEPS} passos; só ferramentas da lista.',
    )


class SkillNameArgs(_Args):
    name: str = Field(min_length=1, max_length=80, description="O nome da habilidade")


class NoArgs(_Args):
    pass


class CreateSkillTool:
    def __init__(self, skills: Skills, check: StepCheck, words: StepWords, catalog: str) -> None:
        self._skills = skills
        self._check = check
        self._words = words
        self._spec = ToolSpec(
            name="create_skill",
            description=(
                "Cria uma habilidade nova juntando ações que você já sabe fazer, quando o "
                "usuário pedir 'quero que você saiba fazer X' ou 'aprenda a X'. Pense nos "
                "passos que fariam isso no PC e mande todos de uma vez. O usuário aprova antes. "
                f"Ferramentas que podem ser passos: {catalog}"
            ),
            args_model=CreateSkillArgs,
            risk=RiskLevel.R1,
            confirm=True,
            timeout_s=10.0,
            group="skills",
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def _parse(self, args: BaseModel) -> Skill | str:
        a = CreateSkillArgs.model_validate(args.model_dump())
        return self._skills.parse(a.name, a.description, a.steps_json, self._check)

    def problem(self, args: BaseModel) -> str | None:
        parsed = self._parse(args)
        return parsed if isinstance(parsed, str) else None

    def describe(self, args: BaseModel) -> str:
        parsed = self._parse(args)
        if isinstance(parsed, str):
            return f"criar uma habilidade ({parsed})"
        return f"criar a habilidade “{parsed.name}”: {steps_preview(parsed, self._words)}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        parsed = self._parse(args)
        if isinstance(parsed, str):
            return ToolResult.failure(parsed)
        return await self._skills.save(parsed)


type Action = Callable[[BaseModel], Awaitable[ToolResult]]


class _SimpleTool:
    def __init__(self, spec: ToolSpec, describe: str, action: Action) -> None:
        self._spec = spec
        self._describe = describe
        self._action = action

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return self._describe

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        return await self._action(args)


def skill_tools(skills: Skills, check: StepCheck, words: StepWords, catalog: str) -> list[Tool]:
    list_spec = ToolSpec(
        name="list_skills",
        description="Lista as habilidades que você aprendeu e os passos de cada uma.",
        args_model=NoArgs,
        risk=RiskLevel.R0,
        group="skills",
    )
    forget_spec = ToolSpec(
        name="forget_skill",
        description="Esquece uma habilidade aprendida.",
        args_model=SkillNameArgs,
        risk=RiskLevel.R1,
        group="skills",
    )

    async def forget(args: BaseModel) -> ToolResult:
        return await skills.forget(SkillNameArgs.model_validate(args.model_dump()).name)

    async def list_all(_args: BaseModel) -> ToolResult:
        return skills.describe(words)

    return [
        CreateSkillTool(skills, check, words, catalog),
        _SimpleTool(list_spec, "listar as habilidades", list_all),
        _SimpleTool(forget_spec, "esquecer uma habilidade", forget),
    ]
