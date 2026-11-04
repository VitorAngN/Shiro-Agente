"""Tier 0 de memória: "lembra que…", "esquece…", "o que você sabe sobre mim?"."""

from __future__ import annotations

from datetime import datetime

import pytest

from shiro.application.memory.rules import MemoryRules
from tests.fakes.agent import SAO_PAULO

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)


rules = MemoryRules(lambda: NOW)


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("lembra que eu torço pro Coritiba", ("remember_fact", {"text": "eu torço pro Coritiba"})),
        (
            "Shiro, guarda que minha irmã se chama Ana",
            ("remember_fact", {"text": "minha irmã se chama Ana"}),
        ),
        ("esquece que eu gosto de café", ("forget_fact", {"query": "eu gosto de café"})),
        ("esquece o que eu falei sobre a Ana", ("forget_fact", {"query": "a Ana"})),
        ("esquece tudo", ("forget_all_memories", {})),
        (
            "lembra que eu prefiro reuniões de manhã",  # parte do dia não é prazo
            ("remember_fact", {"text": "eu prefiro reuniões de manhã"}),
        ),
        ("o que você sabe sobre mim?", ("list_memories", {})),
    ],
)
def test_memory_rules(spoken: str, expected: tuple[str, dict[str, object]]) -> None:
    assert rules(spoken) == [expected]


@pytest.mark.parametrize(
    "spoken",
    [
        "lembra que tenho prova amanhã às 8h",  # tem prazo: atividade, não memória
        "me lembra de tirar a roupa do varal",  # lembrete
        "você lembra de mim?",
        "abre o spotify",
    ],
)
def test_memory_rules_leave_other_things_alone(spoken: str) -> None:
    assert rules(spoken) is None
