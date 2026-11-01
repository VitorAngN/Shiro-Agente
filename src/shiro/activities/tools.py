"""Ferramentas de atividades e lembretes expostas ao agente.

Todas são ``local_only``: títulos e prazos podem ser pessoais e nunca entram
num contexto enviado para a nuvem (ADR-0009, ameaça A-03).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shiro.activities.service import ActivityService
from shiro.core.models import RiskLevel, ToolResult
from shiro.core.ports import ToolContext, ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateActivityArgs(_Args):
    title: str = Field(min_length=1, max_length=200, description="Título curto, sem o prazo")
    due_text: str | None = Field(
        default=None,
        description="Prazo exatamente como o usuário falou ('pra sexta', 'dia 12 às 19h'); "
        "omita se não houver prazo",
    )
    context: str | None = Field(default=None, description="Disciplina ou projeto, se dito")


class ListActivitiesArgs(_Args):
    period: Literal["today", "tomorrow", "this_week", "next_week", "overdue", "all"] = Field(
        default="all", description="Período: hoje, amanhã, esta semana, semana que vem..."
    )


class QueryArgs(_Args):
    query: str = Field(min_length=1, description="Título ou parte do título da atividade")


class PostponeArgs(QueryArgs):
    due_text: str = Field(min_length=1, description="Novo prazo exatamente como o usuário falou")


class RenameArgs(QueryArgs):
    new_title: str = Field(min_length=1, max_length=200, description="Novo título")


class ReminderArgs(_Args):
    text: str = Field(min_length=1, max_length=200, description="O que lembrar, sem o horário")
    when_text: str = Field(
        min_length=1, description="Quando, exatamente como o usuário falou ('às 20h')"
    )


type Action = Callable[[Any], Awaitable[ToolResult]]


class ActivityTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        args_model: type[BaseModel],
        risk: RiskLevel,
        describe: Callable[[Any], str],
        action: Action,
    ) -> None:
        self._spec = ToolSpec(
            name=name,
            description=description,
            args_model=args_model,
            risk=risk,
            timeout_s=5.0,
            local_only=True,
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


def activity_tools(service: ActivityService) -> list[ActivityTool]:
    async def create(a: CreateActivityArgs) -> ToolResult:
        return await service.create(a.title, a.due_text, a.context)

    async def list_(a: ListActivitiesArgs) -> ToolResult:
        return await service.list(a.period)

    async def complete(a: QueryArgs) -> ToolResult:
        return await service.complete(a.query)

    async def postpone(a: PostponeArgs) -> ToolResult:
        return await service.postpone(a.query, a.due_text)

    async def rename(a: RenameArgs) -> ToolResult:
        return await service.rename(a.query, a.new_title)

    async def delete(a: QueryArgs) -> ToolResult:
        return await service.delete(a.query)

    async def remind(a: ReminderArgs) -> ToolResult:
        return await service.remind(a.text, a.when_text)

    return [
        ActivityTool(
            name="create_activity",
            description="Registra uma atividade (trabalho, prova, entrega) com prazo opcional.",
            args_model=CreateActivityArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"anotar {a.title}" + (f" ({a.due_text})" if a.due_text else ""),
            action=create,
        ),
        ActivityTool(
            name="list_activities",
            description="Lista as atividades pendentes de um período.",
            args_model=ListActivitiesArgs,
            risk=RiskLevel.R0,
            describe=lambda a: "listar as atividades",
            action=list_,
        ),
        ActivityTool(
            name="complete_activity",
            description="Marca uma atividade como concluída.",
            args_model=QueryArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"marcar {a.query} como concluída",
            action=complete,
        ),
        ActivityTool(
            name="postpone_activity",
            description="Muda o prazo de uma atividade.",
            args_model=PostponeArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"adiar {a.query} para {a.due_text}",
            action=postpone,
        ),
        ActivityTool(
            name="rename_activity",
            description="Muda o título de uma atividade.",
            args_model=RenameArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"renomear {a.query} para {a.new_title}",
            action=rename,
        ),
        ActivityTool(
            name="delete_activity",
            description="Exclui uma atividade.",
            args_model=QueryArgs,
            risk=RiskLevel.R2,
            describe=lambda a: f"excluir a atividade {a.query}",
            action=delete,
        ),
        ActivityTool(
            name="create_reminder",
            description="Cria um lembrete para um horário.",
            args_model=ReminderArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"te lembrar de {a.text} ({a.when_text})",
            action=remind,
        ),
    ]
