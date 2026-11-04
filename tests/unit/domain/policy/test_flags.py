"""Política: ferramentas que sempre confirmam e as que mandam dados para fora."""

from __future__ import annotations

from shiro.domain.models import DecisionKind, RiskLevel
from shiro.domain.policy.engine import PolicyConfig, PolicyEngine
from shiro.domain.ports import PolicyContext


def test_policy_always_confirm_and_external_with_private_context() -> None:
    engine = PolicyEngine(PolicyConfig(read_only_mode=False))
    assert engine.evaluate(RiskLevel.R2, PolicyContext()).kind is DecisionKind.ALLOW
    confirm = engine.evaluate(RiskLevel.R2, PolicyContext(always_confirm=True))
    assert confirm.kind is DecisionKind.CONFIRM_VOICE
    assert engine.evaluate(RiskLevel.R0, PolicyContext(external=True)).kind is DecisionKind.ALLOW
    private = engine.evaluate(RiskLevel.R0, PolicyContext(external=True, private_context=True))
    assert private.kind is DecisionKind.CONFIRM_VOICE and "dados pessoais" in private.reason
