"""Composition root: o único lugar que conhece todas as peças (ADR-0002).

Monta o agente a partir da configuração, escolhendo os adaptadores concretos.
Tudo que é externo (LLM, HTTP, banco, área de trabalho do Windows) pode ser
substituído por parâmetro, o que permite testar a montagem inteira sem Windows,
sem GPU e sem internet.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from shiro import paths
from shiro.activities.models import Job, parse_offset
from shiro.activities.rules import ActivityRules
from shiro.activities.service import ActivityService
from shiro.activities.tools import activity_tools
from shiro.core.agent import AgentLimits, AgentLoop
from shiro.core.bus import EventBus
from shiro.core.context import ContextBuilder
from shiro.core.events import TurnFinished
from shiro.core.models import Channel, Tier
from shiro.core.ports import Clock, ConfirmationChannel, LLMProvider, Notifier
from shiro.core.router import IntentRouter
from shiro.llm.gemini import GeminiProvider
from shiro.llm.guard import CloudLimits, FallbackProvider, GuardedProvider
from shiro.llm.ollama import OllamaProvider
from shiro.memory.rules import MemoryRules
from shiro.memory.service import MemoryService
from shiro.memory.setup import build_embedder
from shiro.memory.tools import memory_tools
from shiro.persistence.activities import SqliteActivityStore, SqliteJobStore
from shiro.persistence.audit import SqliteAuditLog
from shiro.persistence.conversation import SqliteConversationStore
from shiro.persistence.database import Database
from shiro.persistence.memory import SqliteMemoryStore
from shiro.persistence.usage import SqliteUsageLedger
from shiro.policy.engine import PolicyConfig, PolicyEngine
from shiro.routines import ListRoutinesTool, RoutineRules, load_routines
from shiro.scheduler.runner import Scheduler
from shiro.secrets import get_api_key
from shiro.settings import Settings
from shiro.tools.builtin.apps import AppLauncher, AppTarget, CloseAppTool, OpenAppTool
from shiro.tools.builtin.audio import ChangeVolumeTool, SetVolumeTool, VolumeControl
from shiro.tools.builtin.clock import GetTimeTool
from shiro.tools.builtin.files import AllowedFolders, Trash, file_tools
from shiro.tools.builtin.location import IpLocator, Locator
from shiro.tools.builtin.media import MediaControlTool, MediaKeys
from shiro.tools.builtin.system import PsutilProbe, SystemInfoTool, SystemProbe
from shiro.tools.builtin.weather import WeatherTool
from shiro.tools.builtin.web import GuardedSearch, WebSearchTool
from shiro.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

DATABASE_FILE = "shiro.db"
LOCATION_CACHE_FILE = "location.json"

type Closer = Callable[[], Awaitable[None]]


class SystemClock:
    def __init__(self, timezone: ZoneInfo) -> None:
        self._tz = timezone

    def now(self) -> datetime:
        return datetime.now(self._tz)


class LogNotifier:
    """Avisos só no log; as interfaces (texto, voz, bandeja) trazem o seu."""

    async def notify(self, title: str, message: str) -> None:
        log.info("aviso: %s", message)


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
    return registry


# Palavras que trazem cada grupo de ferramentas para o pedido (texto normalizado, ADR-0018).
TOOL_GATES = {
    "memory": r"\b(?:lembr\w*|esquec\w*|memori\w*|guard\w*|grav\w*|sabe (?:sobre|de) mim)",
    "files": (
        r"\b(?:arquivo\w*|pasta\w*|download\w*|baix[ae]\w*|documento\w*|pdf|planilha\w*|foto\w*"
        r"|imagens?|organiz\w*|lixeira|renome\w*|mov[ea]\w*|apag\w*|restaur\w*|exclu\w*)"
    ),
    "web": (
        r"\b(?:pesquis\w*|internet|google|noticia\w*|procur\w* na|busca na|na web|quem ganhou"
        r"|cotacao|resultado d[oa])"
    ),
}


def build_web_searcher(settings: Settings, ledger: SqliteUsageLedger) -> GuardedSearch | None:
    """Pesquisa na web pelo Gemini, nos mesmos limites do Tier 2 (precisa da chave)."""
    cloud = settings.llm.cloud
    key = get_api_key("gemini") if cloud.enabled else None
    if not key:
        return None
    limits = CloudLimits(
        rpm_limit=cloud.rpm_limit,
        daily_request_limit=cloud.daily_request_limit,
        daily_budget_usd=cloud.daily_budget_usd,
        price_input_per_mtok=cloud.price_input_per_mtok,
        price_output_per_mtok=cloud.price_output_per_mtok,
    )
    gemini = GeminiProvider(api_key=key, model=cloud.model)
    return GuardedSearch(gemini, GuardedProvider(gemini, limits=limits, ledger=ledger))


def build_local_llm(settings: Settings) -> OllamaProvider:
    local = settings.llm.local
    return OllamaProvider(
        host=local.base_url,
        model=local.model,
        num_ctx=local.num_ctx,
        num_gpu=local.num_gpu,
        keep_alive=local.keep_alive,
    )


def build_cloud_llm(
    settings: Settings, ledger: SqliteUsageLedger
) -> tuple[LLMProvider | None, str]:
    """Provedor do Tier 2 e uma frase de estado para mostrar ao usuário."""
    cloud = settings.llm.cloud
    if not cloud.enabled:
        return None, "nuvem desligada no shiro.toml"
    limits = CloudLimits(
        rpm_limit=cloud.rpm_limit,
        daily_request_limit=cloud.daily_request_limit,
        daily_budget_usd=cloud.daily_budget_usd,
        price_input_per_mtok=cloud.price_input_per_mtok,
        price_output_per_mtok=cloud.price_output_per_mtok,
    )
    chain: list[LLMProvider] = []
    for name in (cloud.provider, *cloud.fallback):
        if name != "gemini":
            continue  # adaptadores Anthropic e OpenAI ainda não existem
        key = get_api_key("gemini")
        if key:
            gemini = GeminiProvider(api_key=key, model=cloud.model)
            chain.append(GuardedProvider(gemini, limits=limits, ledger=ledger))
    if not chain:
        return None, f"nuvem sem chave: rode 'shiro secrets set {cloud.provider}'"
    return FallbackProvider(chain), f"nuvem: {cloud.provider}/{cloud.model}"


@dataclass
class App:
    settings: Settings
    agent: AgentLoop
    registry: ToolRegistry
    database: Database
    audit: SqliteAuditLog
    local_llm: LLMProvider
    cloud_llm: LLMProvider | None = None
    cloud_status: str = "nuvem desligada"
    activities: ActivityService | None = None
    scheduler: Scheduler | None = None
    memory: MemoryService | None = None
    trash: Trash | None = None
    problems: list[str] = field(default_factory=list[str])
    """Avisos da montagem (rotina inválida etc.), para a CLI e a bandeja mostrarem."""
    _closers: list[Closer] = field(default_factory=list[Closer])

    def start_background(self) -> None:
        """Liga o agendador de avisos e lembretes e esvazia a lixeira vencida."""
        if self.scheduler is not None:
            self.scheduler.start()
        if self.trash is not None:
            removed = self.trash.purge(timedelta(days=self.settings.retention.trash_days))
            if removed:
                log.info("lixeira: %d itens vencidos apagados", removed)

    async def aclose(self) -> None:
        if self.scheduler is not None:
            await self.scheduler.stop()
        for closer in reversed(self._closers):
            await closer()
        self._closers.clear()


async def build_app(
    settings: Settings,
    *,
    confirmation: ConfirmationChannel,
    database_path: Path | str | None = None,
    data_dir: Path | None = None,
    desktop: Desktop | None = None,
    local_llm: LLMProvider | None = None,
    cloud_llm: LLMProvider | None = None,
    http: httpx.AsyncClient | None = None,
    probe: SystemProbe | None = None,
    notifier: Notifier | None = None,
    clock: Clock | None = None,
    channel: Channel = "text",
) -> App:
    closers: list[Closer] = []

    if http is None:
        http = httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True)
        closers.append(http.aclose)
    if desktop is None:
        desktop = windows_desktop() if sys.platform == "win32" else Desktop()

    data_dir = data_dir or paths.data_dir()
    database = await Database.open(database_path or data_dir / DATABASE_FILE)
    closers.append(database.close)
    audit = SqliteAuditLog(database)
    bus = EventBus()
    bus.subscribe(TurnFinished, SqliteConversationStore(database).on_turn_finished)

    llm = local_llm or build_local_llm(settings)
    providers: dict[Tier, LLMProvider] = {Tier.T1: llm}
    if cloud_llm is not None:
        cloud_status = f"nuvem: {cloud_llm.name}/{cloud_llm.model}"
    else:
        cloud_llm, cloud_status = build_cloud_llm(settings, SqliteUsageLedger(database))
    if cloud_llm is not None:
        providers[Tier.T2] = cloud_llm
    registry = build_registry(
        settings,
        desktop=desktop,
        http=http,
        probe=probe or PsutilProbe(),
        locator=build_locator(settings, http, data_dir),
    )
    clock = clock or SystemClock(ZoneInfo(settings.general.timezone))
    activity_settings = settings.activities
    jobs = SqliteJobStore(database)
    activities = ActivityService(
        store=SqliteActivityStore(database),
        jobs=jobs,
        clock=clock,
        default_due_time=activity_settings.default_due_time,
        alert_offsets=[parse_offset(o) for o in activity_settings.alert_offsets],
        reminder_time=activity_settings.reminder_default_time,
    )
    for tool in activity_tools(activities):
        registry.register(tool)
    memory: MemoryService | None = None
    if settings.memory.enabled:
        memory = MemoryService(
            store=SqliteMemoryStore(database),
            embedder=build_embedder(settings.memory, data_dir),
            clock=clock,
            max_in_context=settings.memory.max_in_context,
            min_score=settings.memory.min_score,
        )
        for memory_tool in memory_tools(memory):
            registry.register(memory_tool)
    folders = AllowedFolders(settings.policy.allowed_folders)
    trash: Trash | None = None
    if folders:
        trash = Trash(data_dir / "trash", clock)
        for file_tool in file_tools(folders, trash, settings.retention.trash_days):
            registry.register(file_tool)
    searcher = build_web_searcher(settings, SqliteUsageLedger(database))
    if searcher is not None:
        registry.register(WebSearchTool(searcher))
    for group, pattern in TOOL_GATES.items():
        registry.gate(group, pattern)
    routines, problems = load_routines(settings.routines, registry)
    registry.register(ListRoutinesTool(routines))
    for problem in problems:
        log.warning(problem)
    notify_with = notifier or LogNotifier()

    async def on_job(job: Job) -> None:
        await activities.handle_job(job, notify_with)

    scheduler = Scheduler(
        jobs=jobs, handlers={"activity_alert": on_job, "reminder": on_job}, clock=clock.now
    )
    agent_settings = settings.agent
    agent = AgentLoop(
        router=IntentRouter(
            apps=app_aliases(settings),
            cloud_triggers=settings.router.cloud_triggers,
            rules=(
                RoutineRules(routines),
                ActivityRules(clock.now),
                *((MemoryRules(clock.now),) if memory is not None else ()),
            ),
        ),
        providers=providers,
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
        clock=clock,
        channel=channel,
        memory=memory,
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
        cloud_llm=cloud_llm,
        cloud_status=cloud_status,
        activities=activities,
        scheduler=scheduler,
        memory=memory,
        trash=trash,
        problems=problems,
        _closers=closers,
    )
