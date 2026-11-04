"""Volume do PC (R1)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args, expect


class VolumeControl(Protocol):
    async def get_level(self) -> int:
        """Volume geral atual, de 0 a 100."""
        ...

    async def set_level(self, level: int) -> None: ...


class SetVolumeArgs(Args):
    level: int = Field(ge=0, le=100, description="Volume de 0 a 100")


class ChangeVolumeArgs(Args):
    delta: int = Field(ge=-100, le=100, description="Variação de -100 a 100")


class SetVolumeTool:
    def __init__(self, control: VolumeControl) -> None:
        self._control = control
        self._spec = ToolSpec(
            name="set_volume",
            description="Define o volume geral do PC.",
            args_model=SetVolumeArgs,
            risk=RiskLevel.R1,
            timeout_s=5.0,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        args = expect(args, SetVolumeArgs)
        return f"definir o volume em {args.level}%"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        args = expect(args, SetVolumeArgs)
        await self._control.set_level(args.level)
        return ToolResult.success(
            f"Volume definido em {args.level}%.", say=f"Volume em {args.level}."
        )


class ChangeVolumeTool:
    def __init__(self, control: VolumeControl) -> None:
        self._control = control
        self._spec = ToolSpec(
            name="change_volume",
            description=(
                "Aumenta ou diminui o volume em relação ao atual. Use 10 ou -10 para 'um pouco'."
            ),
            args_model=ChangeVolumeArgs,
            risk=RiskLevel.R1,
            timeout_s=5.0,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        args = expect(args, ChangeVolumeArgs)
        verb = "aumentar" if args.delta >= 0 else "diminuir"
        return f"{verb} o volume em {abs(args.delta)} pontos"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        args = expect(args, ChangeVolumeArgs)
        current = await self._control.get_level()
        level = max(0, min(100, current + args.delta))
        await self._control.set_level(level)
        return ToolResult.success(
            f"Volume alterado de {current}% para {level}%.", say=f"Volume em {level}."
        )
