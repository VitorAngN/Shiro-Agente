"""Roteador por camadas: Tier 0 por regras, depois o modelo local ou a nuvem."""

from __future__ import annotations

from typing import Any

import pytest

from shiro.application.agent.router import IntentRouter

ROUTER = IntentRouter(
    apps={
        "spotify": ["spotify"],
        "vscode": ["vs code", "visual studio code", "code"],
        "discord": [],
    },
    cloud_triggers=["pensa bem", "pesquisa"],
)


def calls(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    matched = ROUTER.match_tier0(text)
    return None if matched is None else [(c.name, c.arguments) for c in matched]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("abaixa o volume pra 20", [("set_volume", {"level": 20})]),
        ("Ei, Shiro, volume em trinta e cinco por favor", [("set_volume", {"level": 35})]),
        ("coloca o som no 50%", [("set_volume", {"level": 50})]),
        ("volume 0", [("set_volume", {"level": 0})]),
        ("aumenta o volume", [("change_volume", {"delta": 10})]),
        ("abaixa o som um pouco", [("change_volume", {"delta": -10})]),
        ("pula essa música", [("media_control", {"action": "next"})]),
        ("próxima", [("media_control", {"action": "next"})]),
        ("volta a música", [("media_control", {"action": "previous"})]),
        ("pausa a música", [("media_control", {"action": "pause"})]),
        ("volta a tocar", [("media_control", {"action": "play"})]),
        ("que horas são?", [("get_time", {})]),
        ("abre o spotify", [("open_app", {"app": "spotify"})]),
        (
            "abre o VS Code e o Discord",
            [("open_app", {"app": "vscode"}), ("open_app", {"app": "discord"})],
        ),
        ("fecha o discord", [("close_app", {"app": "discord"})]),
        ("como tá o tempo?", [("get_weather", {})]),
        ("Shiro, vai chover hoje?", [("get_weather", {})]),
        ("qual a previsão do tempo pra hoje", [("get_weather", {})]),
        (
            "terminei o trabalho de cálculo",
            [("complete_activity", {"query": "o trabalho de calculo"})],
        ),
        (
            "marca a prova de física como feita",
            [("complete_activity", {"query": "a prova de fisica"})],
        ),
        ("o que eu tenho essa semana?", [("list_activities", {"period": "this_week"})]),
        ("o que eu tenho amanhã", [("list_activities", {"period": "tomorrow"})]),
        ("quais são minhas atividades", [("list_activities", {"period": "all"})]),
        ("tenho alguma coisa hoje?", [("list_activities", {"period": "today"})]),
        ("o que tá atrasado?", [("list_activities", {"period": "overdue"})]),
    ],
)
def test_tier0_matches(text: str, expected: list[tuple[str, dict[str, Any]]]) -> None:
    assert calls(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "volume em 150",  # fora da faixa: o modelo decide o que fazer
        "abre o photoshop",  # app fora da lista
        "abre o spotify e o photoshop",  # uma parte desconhecida invalida tudo
        "tá muito alto, diminui um pouco",
        "quanto de memória ram eu tô usando?",
        "acabei de chegar em casa",  # "acabei de" não é concluir atividade
        "como tá o tempo em Curitiba?",  # cidade explícita: o modelo extrai o argumento
        "",
    ],
)
def test_tier0_falls_through_to_the_model(text: str) -> None:
    assert calls(text) is None


def test_cloud_triggers() -> None:
    assert ROUTER.wants_cloud("Pensa bem: qual a melhor ordem pra estudar?")
    assert not ROUTER.wants_cloud("abre o spotify")


SOUNDS = IntentRouter(
    apps={
        "chrome": ["Chrome", "google chrome"],
        "steam": ["Steam"],
        "discord": ["Discord"],
        "spotify": ["Spotify"],
        "vscode": ["VS Code"],
    },
    cloud_triggers=[],
)


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("Apra o crome.", [("open_app", {"app": "chrome"})]),
        ("abre o stim", [("open_app", {"app": "steam"})]),
        ("abra o istim", [("open_app", {"app": "steam"})]),
        ("fecha o discórdia", [("close_app", {"app": "discord"})]),
        (
            "abra o crome e o stim",
            [("open_app", {"app": "chrome"}), ("open_app", {"app": "steam"})],
        ),
    ],
)
def test_app_names_that_sound_alike(
    spoken: str, expected: list[tuple[str, dict[str, str]]]
) -> None:
    calls = SOUNDS.match_tier0(spoken)
    assert calls is not None and [(c.name, c.arguments) for c in calls] == expected


@pytest.mark.parametrize("spoken", ["Abra, Einstein.", "abra o programa este", "abra o vs"])
def test_does_not_guess_names_that_are_too_different(spoken: str) -> None:
    assert SOUNDS.match_tier0(spoken) is None


def test_taught_alias_is_used_right_away() -> None:
    router = IntentRouter(apps={"steam": ["Steam"]}, cloud_triggers=[])
    assert router.match_tier0("abra einstein") is None
    router.teach_alias("einstein", "steam")
    calls = router.match_tier0("Abra, Einstein.")
    assert calls is not None and calls[0].arguments == {"app": "steam"}
