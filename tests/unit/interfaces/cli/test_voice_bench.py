"""Medidas do bench de voz: taxa de erro de palavras e sentido do comando."""

from __future__ import annotations

import pytest

from shiro.interfaces.cli.voice import command_meaning, word_error_rate


def test_word_error_rate() -> None:
    assert word_error_rate("abre o spotify", "Abre o Spotify.") == 0
    assert word_error_rate("abre o spotify", "abre spotify") == pytest.approx(1 / 3)
    assert word_error_rate("", "") == 0
    assert word_error_rate("", "oi") == 1


def test_command_meaning_compares_deadlines_by_moment() -> None:
    from datetime import datetime

    from shiro.application.activities.rules import ActivityRules
    from shiro.application.agent.router import IntentRouter
    from tests.fakes.agent import SAO_PAULO

    now = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
    router = IntentRouter(apps={}, cloud_triggers=(), rules=(ActivityRules(lambda: now),))

    def meaning(text: str) -> object:
        return command_meaning(router.match_tier0(text), now)

    spoken = "tenho prova de física dia doze às sete da noite"
    assert meaning(spoken) == meaning("Tenho prova de física dia 12 a 7 da noite.")
    assert meaning(spoken) != meaning("Tenho prova de física dia 12 às 7 da manhã.")
    assert meaning("me lembra de tirar a roupa do varal às seis") == meaning(
        "Me lembra de tirar a roupa do varal a 6."
    )
    assert meaning("como vai") is None
