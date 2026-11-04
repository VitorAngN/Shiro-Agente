"""Pesquisa na web: ferramenta, limites da nuvem e fontes do Gemini."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from shiro.domain.ports import LLMError, ToolContext
from shiro.infrastructure.llm.gemini import GeminiProvider, WebAnswer
from shiro.infrastructure.tools.web import GuardedSearch, WebSearchTool
from tests.fakes.agent import SAO_PAULO

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
CTX = ToolContext(trace_id="t", now=NOW)


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
