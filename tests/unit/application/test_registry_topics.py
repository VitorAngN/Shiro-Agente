"""Ferramentas por assunto (ADR-0018): a trie de palavras escolhe os grupos do pedido."""

from __future__ import annotations

from shiro.application.registry import ToolRegistry
from shiro.bootstrap.tools import GATE_EXCEPTIONS, TOOL_GATES
from tests.fakes.agent import FakeTool


def test_tools_are_selected_by_topic() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("get_time"))
    for name, group in (
        ("remember_fact", "memory"),
        ("list_files", "files"),
        ("web_search", "web"),
    ):
        registry.register(FakeTool(name, group=group))
    for group, keywords in TOOL_GATES.items():
        registry.gate(group, keywords)
    registry.except_phrases(GATE_EXCEPTIONS)

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
    registry.gate("files", ["arquivo*"])
    registry.gate("memory", ["lembr*"])
    core = [d.name for d in registry.definitions_for("oi")]
    both = [d.name for d in registry.definitions_for("lembra do arquivo")]
    assert core == ["get_time", "open_app"]
    assert both[: len(core)] == core
    assert both[len(core) :] == ["aaa_list_files", "aaa_remember"]
