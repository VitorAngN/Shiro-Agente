"""Adaptador do Gemini: conteúdos, chamadas de ferramenta, uso e erros."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from google.genai import errors, types

from shiro.domain.models import CompletionRequest, Message, Role, ToolCall, ToolDefinition
from shiro.domain.ports import LLMError
from shiro.infrastructure.llm.gemini import GeminiProvider, from_gemini, to_gemini_contents

SIGNATURE = b"\x01\x02assinatura"


def test_contents_group_tool_results_and_keep_signatures() -> None:
    signed = base64.b64encode(SIGNATURE).decode()
    messages = (
        Message(role=Role.SYSTEM, content="persona"),
        Message(role=Role.USER, content="abre o vs code e o discord"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=(
                ToolCall(id="a", name="open_app", arguments={"app": "vscode"}, signature=signed),
                ToolCall(id="b", name="open_app", arguments={"app": "discord"}),
            ),
        ),
        Message(role=Role.TOOL, content="VS Code aberto.", tool_name="open_app"),
        Message(role=Role.TOOL, content="Discord aberto.", tool_name="open_app"),
        Message(role=Role.ASSISTANT, content="Abri os dois."),
        Message(role=Role.USER, content="valeu"),
    )

    contents = to_gemini_contents(messages)

    assert [c.role for c in contents] == ["user", "model", "user", "model", "user"]
    calls = contents[1].parts or []
    assert calls[0].function_call is not None and calls[0].function_call.args == {"app": "vscode"}
    assert calls[0].thought_signature == SIGNATURE
    assert calls[1].thought_signature is None
    responses = contents[2].parts or []
    assert len(responses) == 2
    assert responses[0].function_response is not None
    assert responses[0].function_response.response == {"result": "VS Code aberto."}


def gemini_response(parts: list[dict[str, Any]], **usage: int) -> types.GenerateContentResponse:
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [{"content": {"role": "model", "parts": parts}}],
            "usage_metadata": {
                "prompt_token_count": usage.get("prompt", 900),
                "candidates_token_count": usage.get("out", 20),
                "thoughts_token_count": usage.get("thoughts", 5),
            },
        }
    )


def test_from_gemini_reads_calls_text_and_usage() -> None:
    response = gemini_response(
        [
            {"text": "pensando...", "thought": True},
            {
                "function_call": {"name": "set_volume", "args": {"level": 30}},
                "thought_signature": base64.b64encode(SIGNATURE).decode(),
            },
        ]
    )

    result = from_gemini(response, model="gemini-3.5-flash-lite", latency_ms=300)

    assert result.text == ""
    assert result.tool_calls[0].name == "set_volume"
    assert result.tool_calls[0].arguments == {"level": 30}
    assert base64.b64decode(result.tool_calls[0].signature or "") == SIGNATURE
    assert result.usage.prompt_tokens == 900
    assert result.usage.completion_tokens == 25


def test_from_gemini_without_candidates_is_an_error() -> None:
    with pytest.raises(LLMError, match="não devolveu resposta"):
        from_gemini(types.GenerateContentResponse(), model="m", latency_ms=1)


class FakeModels:
    def __init__(self, result: types.GenerateContentResponse | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.aio = type("Aio", (), {"models": models})()


REQUEST = CompletionRequest(
    messages=(Message(role=Role.SYSTEM, content="persona"), Message(role=Role.USER, content="oi")),
    tools=(
        ToolDefinition(
            name="get_time",
            description="Hora.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
)


async def test_gemini_complete_sends_system_tools_and_no_auto_calling() -> None:
    models = FakeModels(gemini_response([{"text": "Oi! Na escuta."}]))
    gemini = GeminiProvider(api_key="x", model="gemini-3.5-flash-lite", client=FakeClient(models))  # type: ignore[arg-type]

    result = await gemini.complete(REQUEST)

    call = models.calls[0]
    config: types.GenerateContentConfig = call["config"]
    assert call["model"] == "gemini-3.5-flash-lite"
    assert config.system_instruction == "persona"
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
    assert config.tools is not None
    assert result.text == "Oi! Na escuta."
    assert result.provider == "gemini"


async def test_gemini_api_errors_become_llm_errors() -> None:
    failure = errors.ClientError(
        429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    gemini = GeminiProvider(api_key="x", model="m", client=FakeClient(FakeModels(failure)))  # type: ignore[arg-type]

    with pytest.raises(LLMError, match="Gemini"):
        await gemini.complete(REQUEST)
