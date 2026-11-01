"""Gemini, limites da nuvem, cofre de chaves e comando ``shiro secrets``."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from google.genai import errors, types

from shiro import secrets
from shiro.app import Desktop, build_app, build_cloud_llm
from shiro.cli import _secrets, main  # pyright: ignore[reportPrivateUsage]
from shiro.core.models import CompletionRequest, Message, Role, Tier, ToolCall, ToolDefinition
from shiro.core.ports import LLMError
from shiro.llm.gemini import GeminiProvider, from_gemini, to_gemini_contents
from shiro.llm.guard import CloudLimits, FallbackProvider, GuardedProvider
from shiro.persistence.database import Database
from shiro.persistence.usage import SqliteUsageLedger
from shiro.settings import Settings
from tests.fakes import FakeProvider, reply
from tests.unit.test_tools import FakeProbe

SIGNATURE = b"\x01\x02assinatura"

# ------------------------------------------------------------------ conversões


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


# ------------------------------------------------------------------ limites


class MemoryLedger:
    def __init__(self, requests: int = 0, cost: float = 0.0) -> None:
        self.requests, self.cost = requests, cost
        self.added: list[tuple[str, str, int, int, float]] = []

    async def today(self, provider: str) -> tuple[int, float]:
        return self.requests, self.cost

    async def add(
        self, provider: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float
    ) -> None:
        self.added.append((provider, model, tokens_in, tokens_out, cost_usd))
        self.requests += 1
        self.cost += cost_usd


async def test_guard_records_usage_and_cost() -> None:
    ledger = MemoryLedger()
    limits = CloudLimits(price_input_per_mtok=0.1, price_output_per_mtok=0.4)
    guard = GuardedProvider(FakeProvider([reply("ok")]), limits=limits, ledger=ledger)

    await guard.complete(REQUEST)

    provider, model, tokens_in, tokens_out, cost = ledger.added[0]
    assert (provider, model, tokens_in, tokens_out) == ("fake", "fake-1", 10, 5)
    assert cost == pytest.approx((10 * 0.1 + 5 * 0.4) / 1_000_000)


async def test_guard_enforces_requests_per_minute() -> None:
    now = [0.0]
    guard = GuardedProvider(
        FakeProvider([reply("1"), reply("2"), reply("3")]),
        limits=CloudLimits(rpm_limit=2),
        ledger=MemoryLedger(),
        clock=lambda: now[0],
    )
    await guard.complete(REQUEST)
    await guard.complete(REQUEST)
    with pytest.raises(LLMError, match="por minuto"):
        await guard.complete(REQUEST)

    now[0] = 61.0
    assert (await guard.complete(REQUEST)).text == "3"


@pytest.mark.parametrize(
    ("ledger", "limits", "message"),
    [
        (MemoryLedger(requests=200), CloudLimits(daily_request_limit=200), "limite diário"),
        (MemoryLedger(cost=0.5), CloudLimits(daily_budget_usd=0.5), "orçamento diário"),
    ],
)
async def test_guard_enforces_daily_limits(
    ledger: MemoryLedger, limits: CloudLimits, message: str
) -> None:
    guard = GuardedProvider(FakeProvider([reply("x")]), limits=limits, ledger=ledger)
    with pytest.raises(LLMError, match=message):
        await guard.complete(REQUEST)


async def test_fallback_chain() -> None:
    chain = FallbackProvider(
        [FakeProvider([LLMError("fora")], name="a"), FakeProvider([reply("b")], name="b")]
    )
    assert (await chain.complete(REQUEST)).text == "b"
    assert chain.name == "b"

    everyone_down = FallbackProvider([FakeProvider([LLMError("x")]), FakeProvider([LLMError("y")])])
    with pytest.raises(LLMError, match="x; y"):
        await everyone_down.complete(REQUEST)
    with pytest.raises(ValueError, match="ao menos um"):
        FallbackProvider([])


async def test_sqlite_ledger_accumulates_per_day() -> None:
    database = await Database.open(":memory:")
    day = [date(2026, 11, 1)]
    ledger = SqliteUsageLedger(database, today=lambda: day[0])

    await ledger.add("gemini", "m", 100, 10, 0.001)
    await ledger.add("gemini", "m", 50, 5, 0.002)
    await ledger.add("outro", "m", 1, 1, 1.0)

    requests, cost = await ledger.today("gemini")
    assert requests == 2
    assert cost == pytest.approx(0.003)
    day[0] = date(2026, 11, 2)
    assert await ledger.today("gemini") == (0, 0.0)
    await database.close()


# ------------------------------------------------------------------ montagem e chaves


async def test_cloud_is_off_without_key_and_on_with_key() -> None:
    database = await Database.open(":memory:")
    ledger = SqliteUsageLedger(database)

    provider, status = build_cloud_llm(Settings(), ledger)
    assert provider is None
    assert "shiro secrets set gemini" in status

    secrets.set_api_key("gemini", "chave-de-teste")
    provider, status = build_cloud_llm(Settings(), ledger)
    assert provider is not None
    assert status == "nuvem: gemini/gemini-3.5-flash-lite"

    off = Settings.model_validate({"llm": {"cloud": {"enabled": False}}})
    assert build_cloud_llm(off, ledger)[0] is None
    await database.close()


async def test_cloud_failure_falls_back_to_local(tmp_path: Path) -> None:
    app = await build_app(
        Settings(),
        confirmation=type("No", (), {"ask": staticmethod(lambda *_: False)})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=FakeProvider([reply("Resposta local.")], name="ollama"),
        cloud_llm=FakeProvider([LLMError("cota esgotada")], name="gemini"),
        probe=FakeProbe(),
    )
    try:
        result = await app.agent.run_turn("pensa bem: como organizo a semana?")
        assert result.tier is Tier.T1
        assert result.text == "Resposta local."
    finally:
        await app.aclose()


def test_secrets_round_trip_and_env_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    assert secrets.get_api_key("gemini") is None
    assert secrets.key_source("gemini") is None

    secrets.set_api_key("gemini", "  do-cofre  ")
    assert secrets.get_api_key("gemini") == "do-cofre"
    assert secrets.key_source("gemini") == "cofre"

    monkeypatch.setenv("GEMINI_API_KEY", "do-ambiente")
    assert secrets.get_api_key("gemini") == "do-ambiente"
    assert secrets.key_source("gemini") == "ambiente"

    assert secrets.delete_api_key("gemini")
    assert not secrets.delete_api_key("gemini")
    with pytest.raises(ValueError, match="vazia"):
        secrets.set_api_key("gemini", "   ")
    with pytest.raises(ValueError, match="desconhecido"):
        secrets.get_api_key("deepseek")


def test_secrets_command(capsys: pytest.CaptureFixture[str]) -> None:
    import argparse

    set_args = argparse.Namespace(secrets_command="set", provider="gemini")
    assert _secrets(set_args, prompt=lambda _: "minha-chave") == 0
    assert "guardada" in capsys.readouterr().out
    assert secrets.get_api_key("gemini") == "minha-chave"

    assert main(["secrets", "status"]) == 0
    out = capsys.readouterr().out
    assert "gemini: configurada (cofre)" in out
    assert "minha-chave" not in out  # a chave nunca aparece

    assert main(["config", "check"]) == 0
    assert "chave no cofre" in capsys.readouterr().out

    assert main(["secrets", "delete", "gemini"]) == 0
    assert "apagada" in capsys.readouterr().out
    assert _secrets(set_args, prompt=lambda _: "") == 1
