"""Abrir qualquer programa instalado e trocar de janela pelo nome (ADR-0024).

``open_app`` continua valendo para a lista do ``shiro.toml`` (abrir e fechar).
Aqui entram todos os programas do menu Iniciar, inclusive os da Microsoft Store,
e as janelas abertas: "abre a calculadora", "vai pra janela do Claude".
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Tool, ToolContext, ToolSpec
from shiro.domain.text import closest_name
from shiro.infrastructure.tools._base import Args, expect

# Como o Whisper costuma escrever nomes em inglês → o nome do programa.
SPOKEN_NAMES: dict[str, str] = {
    "cloud": "Claude",
    "clode": "Claude",
    "clóudi": "Claude",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "notepad": "Bloco de Notas",
    "bloco de nota": "Bloco de Notas",
    "explorer": "Explorador de Arquivos",
    "gerenciador de arquivos": "Explorador de Arquivos",
    "gerenciador de tarefas": "Gerenciador de Tarefas",
    "task manager": "Gerenciador de Tarefas",
    "configuracao": "Configurações",
    "settings": "Configurações",
    "calculator": "Calculadora",
}


def spoken_to_name(spoken: str, names: list[str]) -> str | None:
    from shiro.domain.text import normalize

    alias = SPOKEN_NAMES.get(normalize(spoken))
    return closest_name(alias or spoken, names)


class ProgramControl(Protocol):
    def program_names(self) -> list[str]:
        """Programas do menu Iniciar (rápido: lista em cache)."""
        ...

    def window_titles(self) -> list[str]:
        """Títulos das janelas abertas, sem a da SHIRO."""
        ...

    async def launch(self, name: str) -> None: ...

    async def focus(self, title: str) -> None: ...


class ProgramArgs(Args):
    name: str = Field(min_length=1, max_length=80, description="Nome do programa, como foi dito")


class OpenProgramTool:
    spec = ToolSpec(
        name="open_program",
        description=(
            "Abre qualquer programa instalado no PC pelo nome (menu Iniciar e Microsoft Store): "
            "Claude, calculadora, bloco de notas, configurações, jogos..."
        ),
        args_model=ProgramArgs,
        risk=RiskLevel.R1,
        timeout_s=15.0,
        group="control",
    )

    def __init__(self, programs: ProgramControl) -> None:
        self._programs = programs

    def describe(self, args: BaseModel) -> str:
        return f"abrir o programa {expect(args, ProgramArgs).name}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        spoken = expect(args, ProgramArgs).name
        names = self._programs.program_names()
        found = spoken_to_name(spoken, names)
        if found is None:
            return ToolResult.failure(f'Não achei nenhum programa chamado "{spoken}" no PC.')
        await self._programs.launch(found)
        return ToolResult.success(f"{found} aberto.", say=f"Abrindo {found}.")


class SwitchWindowArgs(Args):
    name: str = Field(min_length=1, max_length=80, description="Parte do título da janela")


class SwitchWindowTool:
    spec = ToolSpec(
        name="switch_window",
        description=(
            "Traz para a frente uma janela que já está aberta, pelo nome "
            "('vai pra janela do Claude', 'volta pro Chrome'). Se não estiver aberta, abre."
        ),
        args_model=SwitchWindowArgs,
        risk=RiskLevel.R1,
        timeout_s=15.0,
        group="control",
    )

    def __init__(self, programs: ProgramControl) -> None:
        self._programs = programs

    def describe(self, args: BaseModel) -> str:
        return f"ir para a janela {expect(args, SwitchWindowArgs).name}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        spoken = expect(args, SwitchWindowArgs).name
        title = spoken_to_name(spoken, self._programs.window_titles())
        if title is not None:
            await self._programs.focus(title)
            return ToolResult.success(f"Janela em uso: {title}.", say="Pronto.")
        program = spoken_to_name(spoken, self._programs.program_names())
        if program is not None:
            await self._programs.launch(program)
            return ToolResult.success(
                f"{program} não estava aberto; abri.", say=f"Abrindo {program}."
            )
        return ToolResult.failure(f'Não achei nenhuma janela nem programa "{spoken}".')


class ListWindowsArgs(Args):
    pass


class ListWindowsTool:
    spec = ToolSpec(
        name="list_windows",
        description="Lista as janelas abertas no PC.",
        args_model=ListWindowsArgs,
        risk=RiskLevel.R0,
        timeout_s=10.0,
        output_trusted=False,
        group="control",
    )

    def __init__(self, programs: ProgramControl) -> None:
        self._programs = programs

    def describe(self, args: BaseModel) -> str:
        return "listar as janelas abertas"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        titles = self._programs.window_titles()
        if not titles:
            return ToolResult.success("Nenhuma janela aberta.", say="Não tem janela aberta.")
        return ToolResult.success("Janelas abertas:\n" + "\n".join(f"- {t}" for t in titles))


def program_tools(programs: ProgramControl) -> list[Tool]:
    return [OpenProgramTool(programs), SwitchWindowTool(programs), ListWindowsTool(programs)]
