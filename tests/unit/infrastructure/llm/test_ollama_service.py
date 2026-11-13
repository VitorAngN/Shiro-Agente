"""O motor sobe o Ollama quando ele não está rodando."""

from __future__ import annotations

import httpx

from shiro.infrastructure.llm.ollama_service import OllamaService


def client_for(up: list[bool]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if not up[0]:
            raise httpx.ConnectError("recusado", request=request)
        return httpx.Response(200, json={"version": "0.9"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_already_running_is_left_alone() -> None:
    launched: list[bool] = []
    service = OllamaService(
        "http://x", client=client_for([True]), launch=lambda: launched.append(True) or True
    )
    assert await service.ensure() == "Ollama já estava rodando"
    assert launched == []


async def test_starts_it_and_waits_until_it_answers() -> None:
    up = [False]

    def launch() -> bool:
        up[0] = True
        return True

    service = OllamaService("http://x", client=client_for(up), launch=launch, wait_s=2)
    assert await service.ensure() == "Ollama ligado"


async def test_explains_when_it_is_missing_or_silent() -> None:
    missing = OllamaService("http://x", client=client_for([False]), launch=lambda: False)
    assert "instale" in await missing.ensure()
    silent = OllamaService("http://x", client=client_for([False]), launch=lambda: True, wait_s=0.5)
    assert "não respondeu" in await silent.ensure()
