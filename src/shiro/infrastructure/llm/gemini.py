"""Adaptador do Gemini (Tier 2), usando o SDK oficial ``google-genai`` (ADR-0003).

Converte o formato interno para ``Content``/``Part`` e de volta. As assinaturas
de pensamento (``thought_signature``) que os modelos recentes anexam às chamadas
de ferramenta são guardadas em ``ToolCall.signature`` e devolvidas intactas no
passo seguinte, como a API exige.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

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

_ERRORS = (errors.APIError, httpx.HTTPError, OSError, ValueError)


@dataclass(frozen=True)
class WebAnswer:
    text: str
    sources: tuple[tuple[str, str], ...]
    """(título, endereço) de cada fonte usada."""
    tokens_in: int = 0
    tokens_out: int = 0


class GeminiProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client = client or genai.Client(api_key=api_key)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role is Role.SYSTEM)
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=self._temperature,
            tools=[to_gemini_tool(request.tools)] if request.tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        started = time.perf_counter()
        try:
            response = await self._client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]
                model=self._model, contents=to_gemini_contents(request.messages), config=config
            )
        except _ERRORS as exc:
            msg = f"Gemini ({self._model}): {exc}"
            raise LLMError(msg) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        return from_gemini(response, model=self._model, latency_ms=latency_ms)

    async def search(self, query: str) -> WebAnswer:
        """Pesquisa no Google pelo Gemini (grounding) e resume em português, com fontes."""
        config = types.GenerateContentConfig(
            system_instruction=(
                "Responda em português do Brasil, em até três frases curtas, só com base nos "
                "resultados da busca. Se não achar, diga que não achou."
            ),
            temperature=0.2,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        try:
            response = await self._client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]
                model=self._model, contents=query, config=config
            )
        except _ERRORS as exc:
            msg = f"Gemini ({self._model}): {exc}"
            raise LLMError(msg) from exc
        sources: list[tuple[str, str]] = []
        candidates = response.candidates or []
        metadata = candidates[0].grounding_metadata if candidates else None
        for chunk in (metadata.grounding_chunks or []) if metadata else []:
            web = chunk.web
            if (
                web is not None
                and web.uri
                and (web.title or web.uri) not in (t for t, _ in sources)
            ):
                sources.append((web.title or web.uri, web.uri))
        usage = response.usage_metadata
        return WebAnswer(
            text=(response.text or "").strip(),
            sources=tuple(sources),
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=(usage.candidates_token_count or 0) if usage else 0,
        )

    async def warm_up(self, request: CompletionRequest) -> None:
        """A nuvem não tem modelo para carregar."""

    async def look(self, png: bytes, instruction: str, *, as_json: bool) -> tuple[str, int, int]:
        """Pergunta sobre uma imagem: (texto da resposta, tokens de entrada, tokens de saída)."""
        config = types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json" if as_json else None,
        )
        contents = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=png, mime_type="image/png"),
                types.Part.from_text(text=instruction),
            ],
        )
        try:
            response = await self._client.aio.models.generate_content(  # pyright: ignore[reportUnknownMemberType]
                model=self._model, contents=contents, config=config
            )
        except _ERRORS as exc:
            msg = f"Gemini ({self._model}): {exc}"
            raise LLMError(msg) from exc
        usage = response.usage_metadata
        return (
            (response.text or "").strip(),
            (usage.prompt_token_count or 0) if usage else 0,
            (usage.candidates_token_count or 0) if usage else 0,
        )


def to_gemini_tool(tools: tuple[ToolDefinition, ...]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
    )


def to_gemini_contents(messages: tuple[Message, ...]) -> list[types.Content]:
    """Mensagens internas → ``Content``; respostas de ferramenta seguidas viram um só bloco."""
    contents: list[types.Content] = []
    pending_responses: list[types.Part] = []

    def flush() -> None:
        if pending_responses:
            contents.append(types.Content(role="user", parts=list(pending_responses)))
            pending_responses.clear()

    for message in messages:
        if message.role is Role.SYSTEM:
            continue
        if message.role is Role.TOOL:
            pending_responses.append(
                types.Part.from_function_response(
                    name=message.tool_name or "ferramenta", response={"result": message.content}
                )
            )
            continue
        flush()
        if message.role is Role.USER:
            contents.append(types.Content(role="user", parts=[types.Part(text=message.content)]))
            continue
        parts: list[types.Part] = []
        if message.content:
            parts.append(types.Part(text=message.content))
        for call in message.tool_calls:
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(name=call.name, args=dict(call.arguments)),
                    thought_signature=base64.b64decode(call.signature) if call.signature else None,
                )
            )
        contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
    flush()
    return contents


def from_gemini(
    response: types.GenerateContentResponse, *, model: str, latency_ms: int
) -> CompletionResponse:
    candidates = response.candidates or []
    if not candidates or candidates[0].content is None:
        msg = "Gemini não devolveu resposta (conteúdo bloqueado ou vazio)"
        raise LLMError(msg)
    parts = candidates[0].content.parts or []
    texts: list[str] = []
    calls: list[ToolCall] = []
    for part in parts:
        if part.function_call is not None:
            call = part.function_call
            arguments: dict[str, Any] = dict(call.args or {})
            signature = (
                base64.b64encode(part.thought_signature).decode("ascii")
                if part.thought_signature
                else None
            )
            calls.append(
                ToolCall(
                    id=call.id or f"call_{len(calls)}",
                    name=call.name or "",
                    arguments=arguments,
                    signature=signature,
                )
            )
        elif part.text and not part.thought:
            texts.append(part.text)
    usage = response.usage_metadata
    return CompletionResponse(
        provider="gemini",
        model=model,
        text="".join(texts),
        tool_calls=tuple(calls),
        usage=Usage(
            prompt_tokens=(usage.prompt_token_count or 0) if usage else 0,
            completion_tokens=(
                (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                if usage
                else 0
            ),
        ),
        latency_ms=latency_ms,
    )
