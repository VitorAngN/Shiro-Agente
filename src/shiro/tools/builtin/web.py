"""Pesquisa na web com fontes (RF-32, ADR-0018).

A pergunta sai do PC (vai para o Google pelo Gemini), então a ferramenta é
``external``: num turno com dados pessoais no contexto, ela pede confirmação.
O texto que volta é conteúdo externo (``output_trusted=False``).
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from shiro.core.models import RiskLevel, ToolResult
from shiro.core.ports import LLMError, ToolContext, ToolSpec
from shiro.llm.gemini import WebAnswer
from shiro.tools.builtin._base import Args, expect


class WebSearcher(Protocol):
    async def search(self, query: str) -> WebAnswer: ...


class SearchArgs(Args):
    query: str = Field(
        min_length=2, max_length=200, description="O que pesquisar, em poucas palavras"
    )


def _site(title: str, url: str) -> str:
    """Nome curto da fonte para falar: o título (o Gemini usa o domínio) ou o host."""
    if title and "." in title and " " not in title:
        return title.removeprefix("www.")
    return title or (urlparse(url).hostname or url).removeprefix("www.")


class WebSearchTool:
    spec = ToolSpec(
        name="web_search",
        description=(
            "Pesquisa na internet e resume com fontes. Use só quando o usuário pedir para "
            "pesquisar, ou para notícias e fatos recentes que você não sabe."
        ),
        args_model=SearchArgs,
        risk=RiskLevel.R0,
        timeout_s=30.0,
        output_trusted=False,
        external=True,
        group="web",
    )

    def __init__(self, searcher: WebSearcher | None) -> None:
        self._searcher = searcher

    def describe(self, args: BaseModel) -> str:
        return f'pesquisar na internet "{expect(args, SearchArgs).query}"'

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if self._searcher is None:
            return ToolResult.failure(
                "A pesquisa na web usa o Gemini: configure a chave com 'shiro secrets set gemini'."
            )
        try:
            answer = await self._searcher.search(expect(args, SearchArgs).query)
        except LLMError as exc:
            return ToolResult.failure(f"A pesquisa falhou: {exc}.")
        if not answer.text:
            return ToolResult.failure("Não achei nada sobre isso.")
        sites = list(dict.fromkeys(_site(t, u) for t, u in answer.sources))[:3]
        links = "\n".join(f"- {t}: {u}" for t, u in answer.sources[:5])
        spoken = f"{answer.text} Fontes: {', '.join(sites)}." if sites else answer.text
        content = f"{answer.text}\nFontes:\n{links}" if links else answer.text
        return ToolResult.success(content, say=spoken)


class GuardedSearch:
    """Pesquisa pelo Gemini contando nos mesmos limites e orçamento do Tier 2."""

    def __init__(self, gemini: WebSearcher, guard: object) -> None:
        self._gemini = gemini
        self._guard = guard

    async def search(self, query: str) -> WebAnswer:
        reserve = getattr(self._guard, "reserve", None)
        record = getattr(self._guard, "record", None)
        if reserve is not None:
            await reserve()
        answer = await self._gemini.search(query)
        if record is not None:
            await record(answer.tokens_in, answer.tokens_out)
        return answer
