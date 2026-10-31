"""Controle de mídia (R1).

No Windows, "play" e "pause" usam a mesma tecla de mídia (alterna), então a
resposta fala em "mandar tocar/pausar", sem garantir o estado final.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from shiro.core.models import RiskLevel, ToolResult
from shiro.core.ports import ToolContext, ToolSpec
from shiro.tools.builtin._base import Args, expect

MediaAction = Literal["play", "pause", "next", "previous"]

_DESCRIBE: dict[str, str] = {
    "play": "retomar a mídia",
    "pause": "pausar a mídia",
    "next": "pular para a próxima faixa",
    "previous": "voltar para a faixa anterior",
}
_SAY: dict[str, str] = {
    "play": "Mandei tocar.",
    "pause": "Mandei pausar.",
    "next": "Próxima.",
    "previous": "Voltando.",
}


class MediaKeys(Protocol):
    async def press(self, action: MediaAction) -> None: ...


class MediaArgs(Args):
    action: MediaAction = Field(
        description="play (tocar), pause (pausar), next (próxima) ou previous (anterior)"
    )


class MediaControlTool:
    def __init__(self, keys: MediaKeys) -> None:
        self._keys = keys
        self._spec = ToolSpec(
            name="media_control",
            description="Controla a música ou o vídeo que está tocando no PC.",
            args_model=MediaArgs,
            risk=RiskLevel.R1,
            timeout_s=3.0,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        args = expect(args, MediaArgs)
        return _DESCRIBE[args.action]

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        args = expect(args, MediaArgs)
        await self._keys.press(args.action)
        return ToolResult.success(f"Tecla de mídia enviada: {args.action}.", say=_SAY[args.action])
