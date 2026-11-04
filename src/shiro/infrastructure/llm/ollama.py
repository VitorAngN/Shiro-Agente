"""Adaptador do Ollama (Tier 1), usando o cliente oficial ``ollama`` (ADR-0003).

Converte o formato interno de mensagens e ferramentas para o do Ollama e de
volta. Envia sempre ``num_ctx``, ``num_gpu`` e ``keep_alive`` (ADR-0010 e
ADR-0011).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, cast

import httpx
from ollama import AsyncClient, ChatResponse, RequestError, ResponseError

from shiro.domain.models import (
    CompletionRequest,
    CompletionResponse,
    Message,
    Role,
    ToolCall,
    ToolDefinition,
    Usage,
)
from shiro.domain.ports import LLMError

_ERRORS = (ResponseError, RequestError, httpx.HTTPError, ConnectionError, OSError)


class OllamaProvider:
    def __init__(
        self,
        *,
        host: str,
        model: str,
        num_ctx: int,
        num_gpu: int,
        keep_alive: str,
        temperature: float = 0.0,
        client: AsyncClient | None = None,
    ) -> None:
        self._host = host
        self._model = model
        self._keep_alive = keep_alive
        self._options: dict[str, Any] = {
            "num_ctx": num_ctx,
            "num_gpu": num_gpu,
            "temperature": temperature,
        }
        self._client = client or AsyncClient(
            host=host, timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
        )

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    @property
    def host(self) -> str:
        return self._host

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        started = time.perf_counter()
        response = await self._chat(request, self._options)
        latency_ms = round((time.perf_counter() - started) * 1000)
        return from_ollama(response, model=self._model, latency_ms=latency_ms)

    async def warm_up(self, request: CompletionRequest) -> None:
        await self._chat(request, {**self._options, "num_predict": 1})

    async def release(self) -> None:
        """Tira o modelo da GPU agora (Modo Desempenho, RF-26); volta no próximo pedido."""
        try:
            await self._client.generate(  # pyright: ignore[reportUnknownMemberType]
                model=self._model, prompt="", keep_alive=0
            )
        except _ERRORS as exc:
            msg = f"Ollama ({self._host}): {exc}"
            raise LLMError(msg) from exc

    async def _chat(self, request: CompletionRequest, options: Mapping[str, Any]) -> ChatResponse:
        try:
            response = await self._client.chat(  # pyright: ignore[reportUnknownMemberType]
                model=self._model,
                messages=[to_ollama_message(m) for m in request.messages],
                tools=[to_ollama_tool(t) for t in request.tools] or None,
                options=options,
                keep_alive=self._keep_alive,
                stream=False,
            )
        except _ERRORS as exc:
            msg = f"Ollama ({self._host}): {exc}"
            raise LLMError(msg) from exc
        return response


def to_ollama_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {"function": {"name": call.name, "arguments": call.arguments}}
            for call in message.tool_calls
        ]
    if message.role is Role.TOOL and message.tool_name:
        payload["tool_name"] = message.tool_name
    return payload


def to_ollama_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def from_ollama(response: ChatResponse, *, model: str, latency_ms: int) -> CompletionResponse:
    message = response.message
    calls: list[ToolCall] = []
    for index, call in enumerate(message.tool_calls or ()):
        arguments = cast("Mapping[str, Any]", call.function.arguments or {})
        calls.append(
            ToolCall(id=f"call_{index}", name=call.function.name, arguments=dict(arguments))
        )
    return CompletionResponse(
        provider="ollama",
        model=model,
        text=message.content or "",
        tool_calls=tuple(calls),
        usage=Usage(
            prompt_tokens=response.prompt_eval_count or 0,
            completion_tokens=response.eval_count or 0,
        ),
        latency_ms=latency_ms,
    )
