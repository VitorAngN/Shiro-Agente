"""Modo texto: confirmação no terminal e como cada chamada aparece."""

from __future__ import annotations

from shiro.domain.models import DecisionKind, Tier
from shiro.interfaces.text.session import CliConfirmation, describe_result


async def test_cli_confirmation_parses_answers() -> None:
    assert await CliConfirmation(lambda _: "s").ask("Abrir?", DecisionKind.CONFIRM_VOICE)
    assert await CliConfirmation(lambda _: "Confirmo").ask("Abrir?", DecisionKind.CONFIRM_VOICE)
    assert not await CliConfirmation(lambda _: "").ask("Abrir?", DecisionKind.CONFIRM_PHYSICAL)

    def closed(_: str) -> str:
        raise EOFError

    assert not await CliConfirmation(closed).ask("Abrir?", DecisionKind.CONFIRM_VOICE)


def test_describe_result_marks_blocked_calls() -> None:
    from shiro.domain.models import AgentResult, CallOutcome, ExecutedCall, ToolCall, ToolResult

    blocked = ExecutedCall(
        call=ToolCall(id="c", name="format_disk"),
        risk=None,
        outcome=CallOutcome.BLOCKED,
        reason="x",
        result=ToolResult.failure("não"),
    )
    result = AgentResult(
        text="Não.",
        tier=Tier.T1,
        provider="ollama",
        model="qwen3:4b-instruct",
        calls=(blocked,),
        latency_ms=630,
        claim_blocked=True,
    )
    assert describe_result(result) == (
        "[T1 · ollama/qwen3:4b-instruct · 0,63 s · format_disk ⊘ · ação alegada bloqueada]"
    )
