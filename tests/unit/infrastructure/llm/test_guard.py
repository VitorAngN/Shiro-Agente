"""Limites da nuvem (janela deslizante por minuto, cota diária, custo) e a cadeia de reserva."""

from __future__ import annotations

import pytest

from shiro.domain.models import CompletionRequest, Message, Role, ToolDefinition
from shiro.domain.ports import LLMError
from shiro.infrastructure.llm.guard import CloudLimits, FallbackProvider, GuardedProvider
from tests.fakes.agent import FakeProvider, reply

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
