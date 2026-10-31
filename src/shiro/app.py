"""Composition root: o único lugar que conhece todas as peças (ADR-0002).

Monta o agente a partir da configuração, escolhendo os adaptadores concretos.
Tudo que é externo (LLM, HTTP, banco, área de trabalho do Windows) pode ser
substituído por parâmetro, o que permite testar a montagem inteira sem Windows,
sem GPU e sem internet.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from shiro import paths
from shiro.core.agent import AgentLimits, AgentLoop
from shiro.core.bus import EventBus
from shiro.core.context import ContextBuilder
from shiro.core.events import TurnFinished
from shiro.core.models import Tier
from shiro.core.ports import ConfirmationChannel, LLMProvider
from shiro.core.router import IntentRouter
from shiro.llm.ollama import OllamaProvider
from shiro.persistence.audit import SqliteAuditLog
from shiro.persistence.conversation import SqliteConversationStore
from shiro.persistence.database import Database
from shiro.policy.engine import PolicyConfig, PolicyEngine
from shiro.settings import Settings
from shiro.tools.builtin.apps import AppLauncher, AppTarget, CloseAppTool, OpenAppTool
from shiro.tools.builtin.audio import ChangeVolumeTool, SetVolumeTool, VolumeControl
from shiro.tools.builtin.clock import GetTimeTool
from shiro.tools.builtin.media import MediaControlTool, MediaKeys
from shiro.tools.builtin.system import PsutilProbe, SystemInfoTool, SystemProbe
from shiro.tools.builtin.weather import WeatherTool
from shiro.tools.registry import ToolRegistry

DATABASE_FILE = "shiro.db"

type Closer = Callable[[], Awaitable[None]]


class SystemClock:
    def __init__(self, timezone: ZoneInfo) -> None:
        self._tz = timezone

    def now(self) -> datetime:
        return datetime.now(self._tz)


@dataclass
class Desktop:
    """Adaptadores da área de trabalho. ``None`` desativa a ferramenta correspondente."""

    volume: VolumeControl | None = None
    media: MediaKeys | None = None
    launcher: AppLauncher | None = None


def windows_desktop() -> Desktop:  # pragma: no cover - exercitado no Windows real
    from shiro.tools.windows.apps import WindowsAppLauncher
    from shiro.tools.windows.audio import WindowsVolume
    from shiro.tools.windows.media import WindowsMediaKeys

    return Desktop(volume=WindowsVolume(), media=WindowsMediaKeys(), launcher=WindowsAppLauncher())


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


def build_registry(
    settings: Settings, *, desktop: Desktop, http: httpx.AsyncClient, probe: SystemProbe
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetTimeTool(ZoneInfo(settings.general.timezone)))
    registry.register(SystemInfoTool(probe))
    registry.register(WeatherTool(http, settings.general.city))
    if desktop.volume is not None:
        registry.register(SetVolumeTool(desktop.volume))
        registry.register(ChangeVolumeTool(desktop.volume))
    if desktop.media is not None:
        registry.register(MediaControlTool(desktop.media))
    targets = app_targets(settings)
    if desktop.launcher is not None and targets:
        registry.register(OpenAppTool(targets, desktop.launcher))
        registry.register(CloseAppTool(targets, desktop.launcher))
    return registry


def build_local_llm(settings: Settings) -> OllamaProvider:
    local = settings.llm.local
    return OllamaProvider(
        host=local.base_url,
        model=local.model,
        num_ctx=local.num_ctx,
        num_gpu=local.num_gpu,
        keep_alive=local.keep_alive,
    )


@dataclass
class App:
    settings: Settings
    agent: AgentLoop
    registry: ToolRegistry
    database: Database
    audit: SqliteAuditLog
    local_llm: LLMProvider
    _closers: list[Closer] = field(default_factory=list[Closer])

    async def aclose(self) -> None:
        for closer in reversed(self._closers):
            await closer()
        self._closers.clear()


async def build_app(
    settings: Settings,
    *,
    confirmation: ConfirmationChannel,
    database_path: Path | str | None = None,
    desktop: Desktop | None = None,
    local_llm: LLMProvider | None = None,
    http: httpx.AsyncClient | None = None,
    probe: SystemProbe | None = None,
) -> App:
    closers: list[Closer] = []

    if http is None:
        http = httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True)
        closers.append(http.aclose)
    if desktop is None:
        desktop = windows_desktop() if sys.platform == "win32" else Desktop()

    database = await Database.open(database_path or paths.data_dir() / DATABASE_FILE)
    closers.append(database.close)
    audit = SqliteAuditLog(database)
    bus = EventBus()
    bus.subscribe(TurnFinished, SqliteConversationStore(database).on_turn_finished)

    llm = local_llm or build_local_llm(settings)
    registry = build_registry(settings, desktop=desktop, http=http, probe=probe or PsutilProbe())
    agent_settings = settings.agent
    agent = AgentLoop(
        router=IntentRouter(
            apps=app_aliases(settings), cloud_triggers=settings.router.cloud_triggers
        ),
        providers={Tier.T1: llm},
        tools=registry,
        policy=PolicyEngine(
            PolicyConfig(
                read_only_mode=settings.policy.read_only_mode,
                batch_confirm_threshold=settings.policy.batch_confirm_threshold,
            )
        ),
        confirmation=confirmation,
        audit=audit,
        bus=bus,
        clock=SystemClock(ZoneInfo(settings.general.timezone)),
        context=ContextBuilder(assistant_name=settings.general.assistant_name),
        limits=AgentLimits(
            max_steps=agent_settings.max_steps,
            step_timeout_s=agent_settings.step_timeout_s,
            turn_timeout_s=agent_settings.turn_timeout_s,
            max_history_messages=agent_settings.max_history_messages,
        ),
    )
    return App(
        settings=settings,
        agent=agent,
        registry=registry,
        database=database,
        audit=audit,
        local_llm=llm,
        _closers=closers,
    )
