"""Escrever por voz: texto ou código pronto na janela certa, e o modo ditado (ADR-0026)."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from shiro.application.voice.dictation import Dictation
from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Tool, ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args, expect
from shiro.infrastructure.tools.control import DesktopControl
from shiro.infrastructure.tools.programs import ProgramControl, spoken_to_name

_LAUNCH_WAIT_S = 3.0


class WriteTextArgs(Args):
    content: str = Field(
        min_length=1,
        max_length=8000,
        description="O texto final, já formatado como o usuário pediu (Markdown para notas; "
        "código completo e indentado para código). Sem explicações em volta.",
    )
    window: str | None = Field(
        default=None,
        max_length=80,
        description="Programa onde escrever, se o usuário disse (obsidian, visual studio code, "
        "bloco de notas). Vazio = a janela em uso.",
    )
    enter: bool = Field(default=False, description="Aperta Enter depois (enviar mensagem)")


class WriteTextTool:
    spec = ToolSpec(
        name="write_text",
        description=(
            "Escreve um texto ou um código inteiro de uma vez onde está o cursor (cola). Use "
            "quando o usuário ditar algo para anotar, pedir um código ('escreve uma função "
            "que...') ou pedir para formatar e colocar no Obsidian, VS Code, Word etc. Você "
            "redige e formata; a ferramenta coloca."
        ),
        args_model=WriteTextArgs,
        risk=RiskLevel.R2,
        timeout_s=40.0,
        group="control",
    )

    def __init__(self, control: DesktopControl, programs: ProgramControl | None) -> None:
        self._control = control
        self._programs = programs

    def describe(self, args: BaseModel) -> str:
        parsed = expect(args, WriteTextArgs)
        first = parsed.content.strip().splitlines()[0][:50]
        where = f" no {parsed.window}" if parsed.window else ""
        return f'escrever{where} "{first}..." ({len(parsed.content)} caracteres)'

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        parsed = expect(args, WriteTextArgs)
        if parsed.window and self._programs is not None:
            title = spoken_to_name(parsed.window, self._programs.window_titles())
            if title is not None:
                await self._programs.focus(title)
                await asyncio.sleep(0.3)
            else:
                program = spoken_to_name(parsed.window, self._programs.program_names())
                if program is None:
                    return ToolResult.failure(
                        f'Não achei a janela nem o programa "{parsed.window}". Nada foi escrito.'
                    )
                await self._programs.launch(program)
                await asyncio.sleep(_LAUNCH_WAIT_S)
        await self._control.paste_text(parsed.content)
        if parsed.enter:
            await self._control.press_keys(("enter",))
        lines = parsed.content.count("\n") + 1
        return ToolResult.success(
            f"Escrito ({lines} linhas, {len(parsed.content)} caracteres).", say="Pronto, escrevi."
        )


class NoArgs(Args):
    pass


class StartDictationTool:
    spec = ToolSpec(
        name="start_dictation",
        description=(
            "Liga o modo ditado: tudo o que o usuário falar em seguida é escrito na janela em "
            "uso, até ele dizer 'parar ditado'. Use para 'modo ditado', 'vou ditar'."
        ),
        args_model=NoArgs,
        risk=RiskLevel.R1,
        group="control",
    )

    def __init__(self, dictation: Dictation) -> None:
        self._dictation = dictation

    def describe(self, args: BaseModel) -> str:
        return "ligar o modo ditado"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        self._dictation.requested = True
        message = "Ditado ligado. Pode falar; diga parar ditado para encerrar."
        return ToolResult.success(message, say=message)


def writing_tools(
    control: DesktopControl, programs: ProgramControl | None, dictation: Dictation
) -> list[Tool]:
    return [WriteTextTool(control, programs), StartDictationTool(dictation)]
