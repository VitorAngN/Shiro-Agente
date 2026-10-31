from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from ollama import AsyncClient

from shiro.core.models import CompletionRequest, Message, Role, ToolCall, ToolDefinition
from shiro.core.ports import LLMError
from shiro.llm.ollama import OllamaProvider

HOST = "http://127.0.0.1:11434"


def provider(handler: Any) -> tuple[OllamaProvider, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return handler(request)

    client = AsyncClient(host=HOST, transport=httpx.MockTransport(record))
    ollama = OllamaProvider(
        host=HOST,
        model="qwen3:4b-instruct",
        num_ctx=4096,
        num_gpu=99,
        keep_alive="30m",
        client=client,
    )
    return ollama, sent


def chat_response(message: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen3:4b-instruct",
            "created_at": "2026-10-31T20:00:00Z",
            "message": message,
            "done": True,
            "prompt_eval_count": 1401,
            "eval_count": 12,
        },
    )


REQUEST = CompletionRequest(
    messages=(
        Message(role=Role.SYSTEM, content="persona"),
        Message(role=Role.USER, content="abaixa o volume pra 20"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=(ToolCall(id="c0", name="set_volume", arguments={"level": 20}),),
        ),
        Message(role=Role.TOOL, content="ok", tool_name="set_volume"),
    ),
    tools=(
        ToolDefinition(
            name="set_volume",
            description="Define o volume.",
            parameters={"type": "object", "properties": {"level": {"type": "integer"}}},
        ),
    ),
)


async def test_sends_options_messages_and_tools() -> None:
    ollama, sent = provider(lambda _: chat_response({"role": "assistant", "content": "Pronto."}))

    response = await ollama.complete(REQUEST)

    body = sent[0]
    assert body["model"] == "qwen3:4b-instruct"
    assert body["stream"] is False
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"num_ctx": 4096, "num_gpu": 99, "temperature": 0.0}
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"]
    assert body["messages"][2]["tool_calls"][0]["function"] == {
        "name": "set_volume",
        "arguments": {"level": 20},
    }
    assert body["messages"][3]["tool_name"] == "set_volume"
    assert body["tools"][0]["function"]["name"] == "set_volume"
    assert response.text == "Pronto."
    assert response.usage.prompt_tokens == 1401
    assert response.usage.completion_tokens == 12
    assert response.provider == "ollama"


async def test_parses_tool_calls() -> None:
    ollama, _ = provider(
        lambda _: chat_response(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "open_app", "arguments": {"app": "vscode"}}},
                    {"function": {"name": "open_app", "arguments": {"app": "discord"}}},
                ],
            }
        )
    )

    response = await ollama.complete(REQUEST)

    assert [(c.name, c.arguments) for c in response.tool_calls] == [
        ("open_app", {"app": "vscode"}),
        ("open_app", {"app": "discord"}),
    ]
    assert response.tool_calls[0].id != response.tool_calls[1].id


async def test_warm_up_generates_a_single_token() -> None:
    ollama, sent = provider(lambda _: chat_response({"role": "assistant", "content": "."}))

    await ollama.warm_up(CompletionRequest(messages=(Message(role=Role.SYSTEM, content="p"),)))

    assert sent[0]["options"]["num_predict"] == 1
    assert not sent[0].get("tools")


@pytest.mark.parametrize(
    "failure",
    [
        lambda _: httpx.Response(500, json={"error": "model crashed"}),
        lambda _: httpx.Response(404, json={"error": "model 'x' not found"}),
    ],
)
async def test_server_errors_become_llm_errors(failure: Any) -> None:
    ollama, _ = provider(failure)

    with pytest.raises(LLMError, match="Ollama"):
        await ollama.complete(REQUEST)


async def test_connection_refused_becomes_llm_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    ollama, _ = provider(refuse)

    with pytest.raises(LLMError):
        await ollama.complete(REQUEST)
