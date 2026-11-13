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
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from shiro.application.activities.rules import ActivityRules
from shiro.application.activities.service import ActivityService
from shiro.application.activities.tools import activity_tools
from shiro.application.agent.context import ContextBuilder
from shiro.application.agent.loop import AgentLimits, AgentLoop
from shiro.application.agent.router import IntentRouter
from shiro.application.bus import EventBus
from shiro.application.control.rules import SiteRules
from shiro.application.learning.rules import LearningRules
from shiro.application.learning.service import Lessons
from shiro.application.learning.tools import learning_tools
from shiro.application.memory.rules import MemoryRules
from shiro.application.memory.service import MemoryService
from shiro.application.memory.tools import memory_tools
from shiro.application.registry import ToolRegistry
from shiro.application.routines import ListRoutinesTool, Routine, RoutineRules, load_routines
from shiro.application.scheduler import Scheduler
from shiro.bootstrap.llm import build_cloud_llm, build_local_llm, build_web_searcher
from shiro.bootstrap.tools import (
    GATE_EXCEPTIONS,
    TOOL_GATES,
    Desktop,
    app_aliases,
    build_locator,
    build_registry,
    program_rules,
    windows_desktop,
)
from shiro.config import paths
from shiro.config.settings import Settings
from shiro.domain.activities.models import Job, parse_offset
from shiro.domain.events import TurnFinished
from shiro.domain.memory.embedding import CachedEmbedder
from shiro.domain.models import Channel, Tier
from shiro.domain.policy.engine import PolicyConfig, PolicyEngine
from shiro.domain.ports import Clock, ConfirmationChannel, LLMProvider, Notifier
from shiro.infrastructure.embeddings.setup import build_embedder
from shiro.infrastructure.observability.notifier import LogNotifier
from shiro.infrastructure.persistence.activities import SqliteActivityStore, SqliteJobStore
from shiro.infrastructure.persistence.audit import SqliteAuditLog
from shiro.infrastructure.persistence.conversation import SqliteConversationStore
from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.lessons import SqliteLessonStore
from shiro.infrastructure.persistence.memory import SqliteMemoryStore
from shiro.infrastructure.persistence.usage import SqliteUsageLedger
from shiro.infrastructure.system.clock import SystemClock
from shiro.infrastructure.tools.files import AllowedFolders, Trash, file_tools
from shiro.infrastructure.tools.system import PsutilProbe, SystemProbe
from shiro.infrastructure.tools.web import WebSearchTool

log = logging.getLogger(__name__)


DATABASE_FILE = "shiro.db"


type Closer = Callable[[], Awaitable[None]]


@dataclass
class App:
    settings: Settings
    agent: AgentLoop
    router: IntentRouter
    lessons: Lessons
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
    bus: EventBus | None = None
    routines: dict[str, Routine] = field(default_factory=dict[str, Routine])
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
    problems: list[str] = []
    if database.recovery is not None:
        problems.append(database.recovery.describe())
    await database.daily_backup()
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
    notify_with = notifier or LogNotifier()

    async def on_job(job: Job) -> None:
        await activities.handle_job(job, notify_with)

    scheduler = Scheduler(
        jobs=SqliteJobStore(database),
        handlers={"activity_alert": on_job, "reminder": on_job},
        clock=clock.now,
    )
    activities = ActivityService(
        store=SqliteActivityStore(database),
        jobs=scheduler.watch(SqliteJobStore(database)),
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
            embedder=CachedEmbedder(build_embedder(settings.memory, data_dir)),
            clock=clock,
            max_in_context=settings.memory.max_in_context,
            min_score=settings.memory.min_score,
        )
        for memory_tool in memory_tools(memory):
            registry.register(memory_tool)
    lessons = Lessons(SqliteLessonStore(database), clock)
    await lessons.load()
    for learning_tool in learning_tools(lessons):
        registry.register(learning_tool)
    folders = AllowedFolders(settings.policy.allowed_folders)
    trash: Trash | None = None
    if folders:
        trash = Trash(data_dir / "trash", clock)
        for file_tool in file_tools(folders, trash, settings.retention.trash_days):
            registry.register(file_tool)
    searcher = build_web_searcher(settings, SqliteUsageLedger(database))
    if searcher is not None:
        registry.register(WebSearchTool(searcher))
    for group, keywords in TOOL_GATES.items():
        registry.gate(group, keywords)
    registry.except_phrases(GATE_EXCEPTIONS)
    routines, routine_problems = load_routines(settings.routines, registry)
    registry.register(ListRoutinesTool(routines))
    for problem in routine_problems:
        log.warning(problem)
    problems += routine_problems
    agent_settings = settings.agent
    router = IntentRouter(
        apps=app_aliases(settings),
        cloud_triggers=settings.router.cloud_triggers,
        rules=(
            RoutineRules(routines),
            ActivityRules(clock.now),
            *((MemoryRules(clock.now),) if memory is not None else ()),
            *((SiteRules(),) if registry.get("open_url") is not None else ()),
            *(
                (program_rules(desktop.programs),)
                if desktop.programs is not None and registry.get("open_program") is not None
                else ()
            ),
        ),
        teaching=(LearningRules(),),
        expand=lessons.expand,
    )
    agent = AgentLoop(
        router=router,
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
            cloud_groups=frozenset(settings.router.cloud_groups),
        ),
    )
    return App(
        settings=settings,
        agent=agent,
        router=router,
        lessons=lessons,
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
        bus=bus,
        routines=routines,
        problems=problems,
        _closers=closers,
    )
