from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from shiro.core.models import DecisionKind, RiskLevel
from shiro.core.ports import PolicyContext
from shiro.policy.engine import PolicyConfig, PolicyEngine

ALLOW, VOICE, PHYSICAL, DENY = (
    DecisionKind.ALLOW,
    DecisionKind.CONFIRM_VOICE,
    DecisionKind.CONFIRM_PHYSICAL,
    DecisionKind.DENY,
)
R0, R1, R2, R3, R4 = RiskLevel


@pytest.mark.parametrize(
    ("risk", "read_only", "tainted", "batch", "expected"),
    [
        # modo normal
        (R0, False, False, 1, ALLOW),
        (R1, False, False, 1, ALLOW),
        (R2, False, False, 1, ALLOW),
        (R3, False, False, 1, PHYSICAL),
        (R4, False, False, 1, DENY),
        # lote
        (R2, False, False, 5, ALLOW),
        (R2, False, False, 6, VOICE),
        (R1, False, False, 50, ALLOW),
        # taint endurece R2+, não R0/R1
        (R0, False, True, 1, ALLOW),
        (R1, False, True, 1, ALLOW),
        (R2, False, True, 1, VOICE),
        (R3, False, True, 1, PHYSICAL),
        # somente leitura: tudo com efeito pede confirmação
        (R0, True, False, 1, ALLOW),
        (R1, True, False, 1, VOICE),
        (R2, True, False, 1, VOICE),
        (R3, True, False, 1, PHYSICAL),
        (R4, True, False, 1, DENY),
    ],
)
def test_policy_table(
    risk: RiskLevel, read_only: bool, tainted: bool, batch: int, expected: DecisionKind
) -> None:
    engine = PolicyEngine(PolicyConfig(read_only_mode=read_only, batch_confirm_threshold=5))
    decision = engine.evaluate(risk, PolicyContext(tainted=tainted, batch_size=batch))
    assert decision.kind is expected
    assert decision.reason


@given(
    read_only=st.booleans(),
    tainted=st.booleans(),
    batch=st.integers(min_value=1, max_value=1000),
    threshold=st.integers(min_value=1, max_value=100),
)
def test_r4_is_always_denied(read_only: bool, tainted: bool, batch: int, threshold: int) -> None:
    engine = PolicyEngine(PolicyConfig(read_only_mode=read_only, batch_confirm_threshold=threshold))
    ctx = PolicyContext(tainted=tainted, batch_size=batch)
    assert engine.evaluate(RiskLevel.R4, ctx).kind is DENY
    assert engine.evaluate(RiskLevel.R3, ctx).kind is PHYSICAL
    assert engine.evaluate(RiskLevel.R0, ctx).kind is ALLOW
