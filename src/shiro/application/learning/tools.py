"""Ferramentas do aprendizado expostas ao agente. Todas ``local_only``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shiro.application.learning.service import Lessons
from shiro.domain.learning.models import MAX_MEANING_CHARS
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LessonArgs(_Args):
    trigger: str = Field(
        min_length=1, max_length=80, description="A expressão que o usuário vai dizer ('modo jogo')"
    )
    meaning: str = Field(
        min_length=1,
        max_length=MAX_MEANING_CHARS,
        description="O que ela quer dizer, como um pedido ('feche o discord e abra a steam')",
    )


class TriggerArgs(_Args):
    trigger: str = Field(min_length=1, max_length=80, description="A expressão ensinada")


class NoArgs(_Args):
    pass


class LearningTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        args_model: type[BaseModel],
        risk: RiskLevel,
        describe: Callable[[Any], str],
        action: Callable[[Any], Awaitable[ToolResult]],
    ) -> None:
        self._spec = ToolSpec(
            name=name,
            description=description,
            args_model=args_model,
            risk=risk,
            local_only=True,
            group="learning",
        )
        self._describe = describe
        self._action = action

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return self._describe(args)

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        return await self._action(args)


def learning_tools(lessons: Lessons) -> list[LearningTool]:
    async def learn(a: LessonArgs) -> ToolResult:
        return await lessons.learn(a.trigger, a.meaning)

    async def forget(a: TriggerArgs) -> ToolResult:
        return await lessons.forget(a.trigger)

    async def list_(_: NoArgs) -> ToolResult:
        return await lessons.list()

    return [
        LearningTool(
            name="learn_lesson",
            description=(
                "Ensina uma expressão nova: quando o usuário disser 'trigger', a SHIRO entende "
                "'meaning'. Use só quando ele pedir para aprender ('quando eu disser X, faça Y')."
            ),
            args_model=LessonArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"aprender que “{a.trigger}” quer dizer “{a.meaning}”",
            action=learn,
        ),
        LearningTool(
            name="forget_lesson",
            description="Esquece uma expressão que o usuário ensinou.",
            args_model=TriggerArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"esquecer a expressão “{a.trigger}”",
            action=forget,
        ),
        LearningTool(
            name="list_lessons",
            description="Lista as expressões que o usuário ensinou.",
            args_model=NoArgs,
            risk=RiskLevel.R0,
            describe=lambda _: "listar o que aprendi",
            action=list_,
        ),
    ]
