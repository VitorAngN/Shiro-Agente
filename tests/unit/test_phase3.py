"""Fase 3: arquivos e lixeira, rotinas, pesquisa na web e seleção de ferramentas por assunto."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from shiro.app import TOOL_GATES, Desktop, build_app
from shiro.core.models import DecisionKind, RiskLevel, Tier
from shiro.core.ports import LLMError, PolicyContext, ToolContext
from shiro.llm.gemini import GeminiProvider, WebAnswer
from shiro.policy.engine import PolicyConfig, PolicyEngine
from shiro.routines import ListRoutinesTool, RoutineRules, load_routines
from shiro.settings import RoutineSettings, Settings
from shiro.tools.builtin.files import (
    AllowedFolders,
    FileAccessError,
    FindFilesTool,
    ListFilesTool,
    MoveFileTool,
    OrganizeArgs,
    OrganizeFolderTool,
    RenameFileTool,
    RestoreFileTool,
    Trash,
    TrashFileTool,
    organize_plan,
)
from shiro.tools.builtin.web import GuardedSearch, WebSearchTool
from shiro.tools.registry import ToolRegistry
from tests.fakes import SAO_PAULO, FakeProvider, FakeTool, reply
from tests.unit.test_activities import MovableClock
from tests.unit.test_tools import FakeLauncher, FakeProbe, FakeVolume

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
CTX = ToolContext(trace_id="t", now=NOW)

# ---------------------------------------------------------------------- arquivos


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for index, name in enumerate(
        ["boleto-luz.pdf", "foto praia.JPG", "setup.exe", "notas.txt", "musica.mp3", "x.crdownload"]
    ):
        path = folder / name
        path.write_text(name)
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    (folder / ".escondido").write_text("x")
    return folder


async def test_list_and_find_only_inside_allowed_folders(downloads: Path, tmp_path: Path) -> None:
    folders = AllowedFolders([downloads])
    listed = await ListFilesTool(folders).run(ListFilesTool.spec.args_model(), CTX)
    assert listed.content.startswith("6 em Downloads, mais recentes: x.crdownload; musica.mp3")
    assert ".escondido" not in listed.content
    only_pdf = await ListFilesTool(folders).run(
        ListFilesTool.spec.args_model(folder="downloads", contains="boleto"), CTX
    )
    assert "boleto-luz.pdf" in only_pdf.content and "setup" not in only_pdf.content
    found = await FindFilesTool(folders).run(FindFilesTool.spec.args_model(name="praia"), CTX)
    assert "foto praia.JPG (em Downloads)" in found.content

    other = await ListFilesTool(folders).run(
        ListFilesTool.spec.args_model(folder="documentos"), CTX
    )
    assert not other.ok and "não está liberada" in other.content
    with pytest.raises(FileAccessError):
        folders.check(downloads / ".." / "fora.txt")
    with pytest.raises(FileAccessError, match="nenhuma pasta"):
        AllowedFolders([]).root()
    assert ListFilesTool.spec.output_trusted is False  # nomes de arquivo são conteúdo externo
    assert ListFilesTool.spec.local_only is True


async def test_move_rename_and_refuse_escape(downloads: Path) -> None:
    folders = AllowedFolders([downloads])
    moved = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="boleto", to="Contas"), CTX
    )
    assert moved.ok and (downloads / "Contas" / "boleto-luz.pdf").is_file()
    escape = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="notas", to="../../fora"), CTX
    )
    assert not escape.ok and "fora das pastas" in escape.content
    renamed = await RenameFileTool(folders).run(
        RenameFileTool.spec.args_model(name="notas.txt", new_name="../anotações"), CTX
    )
    assert renamed.ok and (downloads / "anotações.txt").is_file()  # a barra é ignorada
    clash = await RenameFileTool(folders).run(
        RenameFileTool.spec.args_model(name="musica", new_name="setup.exe"), CTX
    )
    assert not clash.ok and "Já existe" in clash.content
    missing = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="nada", to="x"), CTX
    )
    assert not missing.ok


async def test_ambiguous_names_ask_which(downloads: Path) -> None:
    (downloads / "boleto-agua.pdf").write_text("x")
    folders = AllowedFolders([downloads])
    answer = await TrashFileTool(
        folders, Trash(downloads.parent / "lixo", MovableClock(NOW)), 7
    ).run(TrashFileTool.spec.args_model(name="boleto"), CTX)
    assert not answer.ok and "Qual deles?" in answer.content


async def test_trash_restore_and_purge(downloads: Path, tmp_path: Path) -> None:
    clock = MovableClock(NOW)
    trash = Trash(tmp_path / "lixeira", clock)
    folders = AllowedFolders([downloads])
    gone = await TrashFileTool(folders, trash, 7).run(
        TrashFileTool.spec.args_model(name="setup.exe"), CTX
    )
    assert gone.ok and "restaurar por 7 dias" in gone.content
    assert not (downloads / "setup.exe").exists()
    assert [i.name for i in trash.items()] == ["setup.exe"]

    back = await RestoreFileTool(folders, trash).run(
        RestoreFileTool.spec.args_model(name="setup"), CTX
    )
    assert back.ok and (downloads / "setup.exe").read_text() == "setup.exe"
    assert trash.items() == []
    assert not (
        await RestoreFileTool(folders, trash).run(
            RestoreFileTool.spec.args_model(name="setup"), CTX
        )
    ).ok

    await TrashFileTool(folders, trash, 7).run(TrashFileTool.spec.args_model(name="notas"), CTX)
    assert trash.purge(timedelta(days=7)) == 0
    clock.current = NOW + timedelta(days=8)
    assert trash.purge(timedelta(days=7)) == 1
    assert trash.items() == []


async def test_organize_shows_the_plan_before_moving(downloads: Path) -> None:
    folders = AllowedFolders([downloads])
    tool = OrganizeFolderTool(folders)
    assert tool.spec.confirm and tool.spec.risk is RiskLevel.R2
    plan_text = tool.describe(OrganizeArgs(folder="downloads"))
    assert plan_text.startswith("organizar Downloads: mover 5 arquivos (")
    assert "1 em Imagens" in plan_text and "1 em Instaladores" in plan_text
    assert (downloads / "setup.exe").exists()  # descrever não mexe em nada

    done = await tool.run(OrganizeArgs(folder="downloads"), CTX)
    assert done.ok
    assert (downloads / "Imagens" / "foto praia.JPG").is_file()
    assert (downloads / "Documentos" / "boleto-luz.pdf").is_file()
    assert (downloads / "x.crdownload").is_file()  # download em andamento fica onde está
    assert (await tool.run(OrganizeArgs(folder="downloads"), CTX)).content.endswith(
        "já está organizada."
    )
    assert organize_plan([Path("a.xyz")]) == {"Outros": [Path("a.xyz")]}


# ---------------------------------------------------------------------- política


def test_policy_always_confirm_and_external_with_private_context() -> None:
    engine = PolicyEngine(PolicyConfig(read_only_mode=False))
    assert engine.evaluate(RiskLevel.R2, PolicyContext()).kind is DecisionKind.ALLOW
    confirm = engine.evaluate(RiskLevel.R2, PolicyContext(always_confirm=True))
    assert confirm.kind is DecisionKind.CONFIRM_VOICE
    assert engine.evaluate(RiskLevel.R0, PolicyContext(external=True)).kind is DecisionKind.ALLOW
    private = engine.evaluate(RiskLevel.R0, PolicyContext(external=True, private_context=True))
    assert private.kind is DecisionKind.CONFIRM_VOICE and "dados pessoais" in private.reason


# ---------------------------------------------------------------------- web


class FakeSearcher:
    def __init__(self, answer: WebAnswer | Exception) -> None:
        self.answer = answer
        self.queries: list[str] = []

    async def search(self, query: str) -> WebAnswer:
        self.queries.append(query)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_web_search_tool() -> None:
    answer = WebAnswer(
        "O Coritiba venceu por 2 a 1.",
        (("ge.globo.com", "https://ge.globo.com/x"), ("Lance", "https://lance.com.br/y")),
    )
    tool = WebSearchTool(FakeSearcher(answer))
    assert tool.spec.external and not tool.spec.output_trusted and tool.spec.group == "web"
    result = await tool.run(tool.spec.args_model(query="resultado do Coritiba"), CTX)
    assert result.say == "O Coritiba venceu por 2 a 1. Fontes: ge.globo.com, Lance."
    assert "https://lance.com.br/y" in result.content

    assert (
        "shiro secrets set gemini"
        in (await WebSearchTool(None).run(tool.spec.args_model(query="x y"), CTX)).content
    )
    failed = await WebSearchTool(FakeSearcher(LLMError("limite"))).run(
        tool.spec.args_model(query="x y"), CTX
    )
    assert not failed.ok and "limite" in failed.content
    empty = await WebSearchTool(FakeSearcher(WebAnswer("", ()))).run(
        tool.spec.args_model(query="x y"), CTX
    )
    assert not empty.ok


async def test_guarded_search_counts_in_cloud_limits() -> None:
    events: list[str] = []

    class Guard:
        async def reserve(self) -> None:
            events.append("reserve")

        async def record(self, tokens_in: int, tokens_out: int) -> None:
            events.append(f"record {tokens_in}/{tokens_out}")

    searcher = GuardedSearch(FakeSearcher(WebAnswer("ok", (), 12, 34)), Guard())
    await searcher.search("teste")
    assert events == ["reserve", "record 12/34"]


async def test_gemini_search_reads_grounding_sources() -> None:
    web = SimpleNamespace(uri="https://ge.globo.com/a", title="ge.globo.com")
    response = SimpleNamespace(
        text=" Venceu. ",
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[SimpleNamespace(web=web), SimpleNamespace(web=web)]
                )
            )
        ],
        usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=7),
    )
    seen: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return response

    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    gemini = GeminiProvider(api_key="x", model="m", client=client)  # type: ignore[arg-type]
    answer = await gemini.search("quem ganhou?")
    assert answer == WebAnswer("Venceu.", (("ge.globo.com", "https://ge.globo.com/a"),), 5, 7)
    assert seen["config"].tools[0].google_search is not None


# ---------------------------------------------------------------------- rotinas


def study_routine() -> dict[str, RoutineSettings]:
    return {
        "estudo": RoutineSettings.model_validate(
            {
                "description": "fecha distrações e abre o VS Code",
                "aliases": ["hora de estudar"],
                "steps": [
                    {"tool": "close_app", "args": {"app": "discord"}},
                    {"tool": "open_app", "args": {"app": "vscode"}},
                    {"tool": "set_volume", "args": {"level": 30}},
                ],
            }
        ),
        "quebrada": RoutineSettings.model_validate(
            {"steps": [{"tool": "nao_existe"}, {"tool": "set_volume", "args": {"level": 900}}]}
        ),
    }


class AppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str


class LevelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=0, le=100)


def test_routines_are_validated_against_real_tools() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("close_app", args_model=AppArgs))
    registry.register(FakeTool("open_app", args_model=AppArgs))
    registry.register(FakeTool("set_volume", args_model=LevelArgs))
    routines, problems = load_routines(study_routine(), registry)
    assert list(routines) == ["estudo"]
    assert len(problems) == 1 and problems[0].startswith("rotina quebrada desligada")
    rules = RoutineRules(routines)
    for spoken in (
        "modo estudo",
        "Ei Shiro, ativa o modo estudo",
        "hora de estudar",
        "rotina estudo",
    ):
        calls = rules(spoken)
        assert calls is not None and [c[0] for c in calls] == [
            "close_app",
            "open_app",
            "set_volume",
        ]
    assert rules("estudo") is None  # uma palavra solta não liga a rotina
    assert rules("modo avião") is None


async def test_study_mode_end_to_end(tmp_path: Path) -> None:
    launcher, volume = FakeLauncher(), FakeVolume()
    settings = Settings.model_validate(
        {
            "policy": {
                "read_only_mode": False,
                "allowed_apps": {
                    "discord": {"launch": "discord:", "process": "Discord.exe"},
                    "vscode": "code",
                },
                "allowed_folders": [],
            },
            "routines": {k: v.model_dump() for k, v in study_routine().items()},
        }
    )
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(volume=volume, launcher=launcher),
        local_llm=FakeProvider([]),
        probe=FakeProbe(),
    )
    try:
        assert app.problems and "quebrada" in app.problems[0]
        result = await app.agent.run_turn("ativa o modo estudo")
        assert result.tier is Tier.T0
        assert [c.call.name for c in result.calls] == ["close_app", "open_app", "set_volume"]
        assert all(c.result.ok for c in result.calls)
        assert launcher.launched == ["code"] and volume.level == 30
        listed = await ListRoutinesTool({}).run(ListRoutinesTool.spec.args_model(), CTX)
        assert "Nenhuma rotina" in listed.content
        assert app.registry.get("list_files") is None  # sem pasta liberada, sem ferramentas
    finally:
        await app.aclose()


async def _true() -> bool:
    return True


# ---------------------------------------------------------------------- seleção por assunto


def test_tools_are_selected_by_topic() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("get_time"))
    for name, group in (
        ("remember_fact", "memory"),
        ("list_files", "files"),
        ("web_search", "web"),
    ):
        registry.register(FakeTool(name, group=group))
    for group, pattern in TOOL_GATES.items():
        registry.gate(group, pattern)

    def names(text: str, extra: frozenset[str] = frozenset()) -> list[str]:
        return [d.name for d in registry.definitions_for(text, extra)]

    assert names("que horas são?") == ["get_time"]
    assert names("quanto de memória ram eu tô usando?") == ["get_time"]
    assert names("lembra que eu gosto de café") == ["get_time", "remember_fact"]
    assert names("organiza meus downloads") == ["get_time", "list_files"]
    assert names("pesquisa na internet o resultado do jogo") == ["get_time", "web_search"]
    assert names("e o outro?", frozenset({"files"})) == ["get_time", "list_files"]
    assert registry.definitions_for("x") is registry.definitions_for("y")  # cache por conjunto
    assert registry.group_of("list_files") == "files" and registry.group_of("nada") is None


async def test_agent_remembers_recent_groups_for_follow_ups(tmp_path: Path) -> None:
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "a.pdf").write_text("x")
    local = FakeProvider(
        [
            reply("", ("list_files", {})),
            reply("Tem um PDF."),
            reply("Ok."),
        ]
    )
    settings = Settings.model_validate(
        {"policy": {"read_only_mode": False, "allowed_folders": [str(tmp_path / "Downloads")]}}
    )
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=local,
        probe=FakeProbe(),
    )
    try:
        await app.agent.run_turn("o que tem nos meus downloads?")
        await app.agent.run_turn("e qual é o mais novo?")
        first = {d.name for d in local.requests[0].tools}
        follow_up = {d.name for d in local.requests[2].tools}
        assert "list_files" in first and "list_files" in follow_up
        app.agent.reset()
        assert app.agent._recent_groups() == frozenset()  # pyright: ignore[reportPrivateUsage]
    finally:
        await app.aclose()


@pytest.mark.skipif(sys.platform == "win32", reason="permissões de link simbólico no Windows")
def test_symlinks_out_of_the_folder_are_ignored(downloads: Path, tmp_path: Path) -> None:
    outside = tmp_path / "segredo.txt"
    outside.write_text("x")
    (downloads / "atalho.txt").symlink_to(outside)
    folders = AllowedFolders([downloads])
    assert "atalho.txt" not in [p.name for p in folders.files(downloads)]
    with pytest.raises(FileAccessError):
        folders.check(downloads / "atalho.txt")


def test_extra_groups_go_after_the_core_tools() -> None:
    """O prefixo (persona + núcleo) não muda entre turnos: o cache de prefixo continua valendo."""
    registry = ToolRegistry()
    for name, group in (
        ("aaa_list_files", "files"),
        ("get_time", "core"),
        ("open_app", "core"),
        ("aaa_remember", "memory"),
    ):
        registry.register(FakeTool(name, group=group))
    registry.gate("files", r"arquivo")
    registry.gate("memory", r"lembr")
    core = [d.name for d in registry.definitions_for("oi")]
    both = [d.name for d in registry.definitions_for("lembra do arquivo")]
    assert core == ["get_time", "open_app"]
    assert both[: len(core)] == core
    assert both[len(core) :] == ["aaa_list_files", "aaa_remember"]
