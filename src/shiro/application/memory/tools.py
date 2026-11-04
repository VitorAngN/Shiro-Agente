"""Ferramentas de memória expostas ao agente. Todas ``local_only``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shiro.application.memory.service import MemoryService
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FactArgs(_Args):
    text: str = Field(
        min_length=1,
        max_length=300,
        description="O fato como o usuário falou, em uma frase ('eu torço pro Coritiba')",
    )


class QueryArgs(_Args):
    query: str = Field(min_length=1, description="Do que é a memória ('time de futebol')")


class NoArgs(_Args):
    pass


class MemoryTool:
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
            timeout_s=20.0,  # a primeira chamada carrega o modelo de embedding
            local_only=True,
            group="memory",
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


def memory_tools(service: MemoryService) -> list[MemoryTool]:
    async def remember(a: FactArgs) -> ToolResult:
        return await service.remember(a.text)

    async def forget(a: QueryArgs) -> ToolResult:
        return await service.forget(a.query)

    async def forget_all(_: NoArgs) -> ToolResult:
        return await service.forget_all()

    async def list_(_: NoArgs) -> ToolResult:
        return await service.list()

    return [
        MemoryTool(
            name="remember_fact",
            description=(
                "Guarda um fato ou preferência que o usuário pediu explicitamente para lembrar "
                "('lembra que...'). Não use para tarefas com prazo nem lembretes com horário."
            ),
            args_model=FactArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"guardar na memória: {a.text}",
            action=remember,
        ),
        MemoryTool(
            name="forget_fact",
            description="Apaga uma memória quando o usuário pede para esquecer algo.",
            args_model=QueryArgs,
            risk=RiskLevel.R1,
            describe=lambda a: f"esquecer {a.query}",
            action=forget,
        ),
        MemoryTool(
            name="forget_all_memories",
            description="Apaga todas as memórias. Só quando o usuário pedir para esquecer tudo.",
            args_model=NoArgs,
            risk=RiskLevel.R2,
            describe=lambda _: "apagar todas as memórias",
            action=forget_all,
        ),
        MemoryTool(
            name="list_memories",
            description="Lista o que está guardado na memória sobre o usuário.",
            args_model=NoArgs,
            risk=RiskLevel.R0,
            describe=lambda _: "listar as memórias",
            action=list_,
        ),
    ]
