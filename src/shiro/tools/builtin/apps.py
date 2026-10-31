"""Abrir (R1) e fechar (R2) aplicativos da lista permitida.

A lista vem do ``shiro.toml``. Os argumentos aceitam só as chaves dessa lista,
então um app fora dela nem chega a ser um argumento válido (ADR-0005).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, create_model

from shiro.core.models import RiskLevel, ToolResult
from shiro.core.ports import ToolContext, ToolSpec
from shiro.tools.builtin._base import Args


class AppTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    launch: str
    process: str = ""


class AppLauncher(Protocol):
    async def launch(self, target: str) -> None: ...

    async def close(self, process: str) -> int:
        """Encerra os processos com esse nome; devolve quantos foram encerrados."""
        ...


def app_args_model(apps: Mapping[str, AppTarget]) -> type[Args]:
    """Modelo de argumentos com ``app`` restrito às chaves configuradas."""
    if not apps:
        msg = "nenhum app configurado"
        raise ValueError(msg)
    names = tuple(sorted(apps))
    labels = ", ".join(f"{key} ({apps[key].label})" for key in names)
    app_type = cast("Any", Literal).__getitem__(names)
    return create_model(
        "AppArgs",
        __base__=Args,
        app=(app_type, Field(description=f"Aplicativo: {labels}")),
    )


class _AppTool:
    def __init__(
        self, apps: Mapping[str, AppTarget], launcher: AppLauncher, spec: ToolSpec
    ) -> None:
        self._apps = dict(apps)
        self._launcher = launcher
        self._spec = spec

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def _target(self, args: BaseModel) -> AppTarget:
        return self._apps[str(args.model_dump()["app"])]


class OpenAppTool(_AppTool):
    def __init__(self, apps: Mapping[str, AppTarget], launcher: AppLauncher) -> None:
        spec = ToolSpec(
            name="open_app",
            description="Abre um aplicativo da lista permitida.",
            args_model=app_args_model(apps),
            risk=RiskLevel.R1,
            timeout_s=10.0,
        )
        super().__init__(apps, launcher, spec)

    def describe(self, args: BaseModel) -> str:
        return f"abrir o {self._target(args).label}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        target = self._target(args)
        await self._launcher.launch(target.launch)
        return ToolResult.success(f"{target.label} aberto.", say=f"Abrindo o {target.label}.")


class CloseAppTool(_AppTool):
    def __init__(self, apps: Mapping[str, AppTarget], launcher: AppLauncher) -> None:
        spec = ToolSpec(
            name="close_app",
            description="Fecha um aplicativo da lista permitida.",
            args_model=app_args_model(apps),
            risk=RiskLevel.R2,
            timeout_s=10.0,
        )
        super().__init__(apps, launcher, spec)

    def describe(self, args: BaseModel) -> str:
        return f"fechar o {self._target(args).label}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        target = self._target(args)
        if not target.process:
            return ToolResult.failure(
                f"Não sei qual processo fechar para o {target.label}. "
                "Configure 'process' desse app no shiro.toml."
            )
        closed = await self._launcher.close(target.process)
        if closed == 0:
            return ToolResult.failure(f"O {target.label} não estava aberto.")
        return ToolResult.success(f"{target.label} fechado.", say=f"Fechei o {target.label}.")
