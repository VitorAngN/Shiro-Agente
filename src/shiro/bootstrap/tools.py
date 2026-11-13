"""Montagem das ferramentas: adaptadores do Windows, registro e palavras por assunto."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from shiro.application.control.rules import ProgramRules
from shiro.application.registry import ToolRegistry
from shiro.application.voice.dictation import Dictation
from shiro.config.settings import Settings
from shiro.infrastructure.tools.apps import AppLauncher, AppTarget, CloseAppTool, OpenAppTool
from shiro.infrastructure.tools.audio import ChangeVolumeTool, SetVolumeTool, VolumeControl
from shiro.infrastructure.tools.clock import GetTimeTool
from shiro.infrastructure.tools.control import DesktopControl, control_tools
from shiro.infrastructure.tools.location import IpLocator, Locator
from shiro.infrastructure.tools.media import MediaControlTool, MediaKeys
from shiro.infrastructure.tools.programs import ProgramControl, program_tools, spoken_to_name
from shiro.infrastructure.tools.system import SystemInfoTool, SystemProbe
from shiro.infrastructure.tools.weather import WeatherTool
from shiro.infrastructure.tools.writing import writing_tools
from shiro.infrastructure.tools.youtube import YouTubeFinder

LOCATION_CACHE_FILE = "location.json"


@dataclass
class Desktop:
    """Adaptadores da área de trabalho. ``None`` desativa a ferramenta correspondente."""

    volume: VolumeControl | None = None
    media: MediaKeys | None = None
    launcher: AppLauncher | None = None
    control: DesktopControl | None = None
    programs: ProgramControl | None = None


def windows_desktop() -> Desktop:  # pragma: no cover - exercitado no Windows real
    from shiro.infrastructure.tools.windows.apps import WindowsAppLauncher
    from shiro.infrastructure.tools.windows.audio import WindowsVolume
    from shiro.infrastructure.tools.windows.control import (
        WindowsDesktopControl,
        enable_dpi_awareness,
    )
    from shiro.infrastructure.tools.windows.media import WindowsMediaKeys
    from shiro.infrastructure.tools.windows.programs import WindowsPrograms

    enable_dpi_awareness()
    return Desktop(
        volume=WindowsVolume(),
        media=WindowsMediaKeys(),
        launcher=WindowsAppLauncher(),
        control=WindowsDesktopControl(),
        programs=WindowsPrograms(),
    )


def app_targets(settings: Settings) -> dict[str, AppTarget]:
    return {
        key: AppTarget(key=key, label=entry.label, launch=entry.launch, process=entry.process_name)
        for key, entry in settings.policy.allowed_apps.items()
    }


def app_aliases(settings: Settings) -> dict[str, list[str]]:
    return {
        key: [alias for alias in (entry.name, *entry.aliases) if alias]
        for key, entry in settings.policy.allowed_apps.items()
    }


def build_locator(settings: Settings, http: httpx.AsyncClient, data_dir: Path) -> Locator | None:
    """Localizador para o clima: só quando não há cidade fixa e a detecção está ligada."""
    general = settings.general
    if general.city.strip() or general.location == "off":
        return None
    return IpLocator(http, data_dir / LOCATION_CACHE_FILE)


def build_registry(
    settings: Settings,
    *,
    desktop: Desktop,
    http: httpx.AsyncClient,
    probe: SystemProbe,
    locator: Locator | None = None,
    dictation: Dictation | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetTimeTool(ZoneInfo(settings.general.timezone)))
    registry.register(SystemInfoTool(probe))
    registry.register(WeatherTool(http, settings.general.city, locator))
    if desktop.volume is not None:
        registry.register(SetVolumeTool(desktop.volume))
        registry.register(ChangeVolumeTool(desktop.volume))
    if desktop.media is not None:
        registry.register(MediaControlTool(desktop.media))
    targets = app_targets(settings)
    if desktop.launcher is not None and targets:
        registry.register(OpenAppTool(targets, desktop.launcher))
        registry.register(CloseAppTool(targets, desktop.launcher))
    if desktop.control is not None and settings.policy.pc_control:
        for tool in control_tools(desktop.control, YouTubeFinder(http)):
            registry.register(tool)
    if desktop.control is not None and settings.policy.pc_control:
        dictation = dictation or Dictation(desktop.control.paste_text)
        for tool in writing_tools(desktop.control, desktop.programs, dictation):
            registry.register(tool)
    if desktop.programs is not None and settings.policy.pc_control:
        for tool in program_tools(desktop.programs):
            registry.register(tool)
    return registry


# Palavras que trazem cada grupo de ferramentas para o pedido (texto normalizado, ADR-0018).
# Palavras de cada assunto (sobre o texto normalizado). "*" no fim: radical.
TOOL_GATES: dict[str, tuple[str, ...]] = {
    # Habilidades: "quero que você saiba fazer X" (ADR-0025).
    "skills": (
        "habilidade*",
        "saiba fazer",
        "saber fazer",
        "seja capaz",
        "ser capaz",
        "capaz de",
        "aprenda a",
        "aprende a",
        "aprender a",
        "consiga fazer",
        "conseguir fazer",
        "que voce saiba",
        "quero que voce consiga",
    ),
    "learning": (
        "aprend*",
        "desaprend*",
        "ensin*",
        "quando eu disser",
        "quando eu falar",
        "sempre que eu",
    ),
    "memory": (
        "lembr*",
        "esquec*",
        "memoria*",
        "guard*",
        "grav*",
        "sabe sobre mim",
        "sabe de mim",
    ),
    "files": (
        "arquivo*",
        "pasta*",
        "download*",
        "baixa*",
        "baixe*",
        "documento*",
        "pdf*",
        "planilha*",
        "foto*",
        "imagem*",
        "imagen*",
        "organiz*",
        "lixeira*",
        "renome*",
        "move*",
        "mova*",
        "apag*",
        "restaur*",
        "exclu*",
    ),
    # Controlar o PC: sites no navegador, digitar, teclas, ler a tela e clicar (ADR-0024).
    "control": (
        "clica*",
        "clique*",
        "clicar",
        "aperta*",
        "aperte*",
        "pressiona*",
        "digit*",
        "escrev*",
        "tecla*",
        "atalho*",
        "site*",
        "pagina*",
        "navegador*",
        "link*",
        "url",
        "endereco",
        "youtube*",
        "toca*",
        "toque*",
        "tocar",
        "coloca*",
        "coloque*",
        "video*",
        "wikipedia*",
        "github*",
        "chrome*",
        "edge",
        "firefox*",
        "brave",
        "opera",
        "na tela",
        "da tela",
        "a tela",
        "janela*",
        "ditado",
        "ditar",
        "dita",
        "codigo*",
        "funcao*",
        "no obsidian",
        "no vscode",
        "no vs code",
        "no visual studio",
        "no bloco de notas",
        "no word",
        "no notion",
        "abre*",
        "abra*",
        "abrir",
        "inicia*",
        "executa*",
        "programa*",
        "aplicativo*",
        "vai pra",
        "vai pro",
        "volta pra",
        "volta pro",
        "muda pra",
        "muda pro",
        "troca pra",
        "troca pro",
        "botao*",
        "entra no",
        "entra na",
        "entre no",
        "entre na",
        "acessa*",
        "acesse*",
        "pesquisa no",
        "pesquisa na",
        "pesquise no",
        "pesquise na",
        "procura no",
        "procure no",
        "enter",
        "ctrl",
        "esc",
    ),
    "web": (
        "pesquis*",
        "internet*",
        "google*",
        "noticia*",
        "procura na",
        "procure na",
        "procurar na",
        "procurando na",
        "busca na",
        "busca nas",
        "na web",
        "quem ganhou",
        "cotacao",
        "cotacoes",
        "resultado do",
        "resultado da",
        "resultado dos",
        "resultado das",
    ),
}
# "memória RAM" é do sistema, não da SHIRO: a frase mais longa vence o radical "memoria*".
GATE_EXCEPTIONS = (
    "memoria ram",
    "memoria do pc",
    "memoria do computador",
    "memoria livre",
    "memoria usada",
)


def program_rules(programs: ProgramControl) -> ProgramRules:
    """Tier 0 de programas e janelas, com os nomes reais do menu Iniciar e das janelas."""
    return ProgramRules(
        program=lambda spoken: spoken_to_name(spoken, programs.program_names()),
        window=lambda spoken: spoken_to_name(spoken, programs.window_titles()),
    )
