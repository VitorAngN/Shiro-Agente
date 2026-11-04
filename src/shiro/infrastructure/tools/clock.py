"""Data e hora (R0)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import BaseModel

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args

WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


class GetTimeArgs(Args):
    pass


class GetTimeTool:
    def __init__(self, timezone: ZoneInfo) -> None:
        self._tz = timezone
        self._spec = ToolSpec(
            name="get_time",
            description="Informa a data e a hora atuais.",
            args_model=GetTimeArgs,
            risk=RiskLevel.R0,
            timeout_s=1.0,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return "informar a data e a hora"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        now = ctx.now.astimezone(self._tz)
        hour = f"{now.hour}h{now.minute:02d}"
        day = f"{WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]}"
        return ToolResult.success(
            f"Agora são {hour} de {day} de {now.year}.", say=f"São {hour} de {day}."
        )
