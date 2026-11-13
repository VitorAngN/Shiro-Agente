"""Tier 0 dos sites: abrir e pesquisar sem passar pelo modelo."""

from __future__ import annotations

import pytest

from shiro.application.agent.router import IntentRouter
from shiro.application.control.rules import SiteRules, site_phrases
from shiro.application.voice.commands import CommandCatalog

RULES = SiteRules()


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("abre o youtube", "youtube.com"),
        ("Shiro, abre o YouTube.", "youtube.com"),
        ("abra o iutubi", "youtube.com"),
        ("entra no site do github", "github.com"),
        ("vai pro whatsapp por favor", "web.whatsapp.com"),
        ("abre a wikipedia", "pt.wikipedia.org"),
        ("acessa o twitter", "x.com"),
    ],
)
def test_open_known_sites(text: str, url: str) -> None:
    assert RULES(text) == [("open_url", {"url": url})]


def test_search_keeps_the_spoken_words() -> None:
    assert RULES("Pesquisa Hollow Knight no YouTube.") == [
        ("open_url", {"search": "Hollow Knight", "on": "youtube"})
    ]
    assert RULES("procura São Paulo na Wikipédia") == [
        ("open_url", {"search": "São Paulo", "on": "wikipedia"})
    ]


@pytest.mark.parametrize(
    "text",
    ["abre a pasta downloads", "pesquisa o preço do dólar", "abre o netflix e o spotify", "oi"],
)
def test_other_requests_go_to_the_model(text: str) -> None:
    assert RULES(text) is None


def test_router_prefers_apps_then_sites() -> None:
    router = IntentRouter(
        apps={"chrome": ["google chrome"], "steam": []}, cloud_triggers=[], rules=(RULES,)
    )
    calls = router.match_tier0("abre o chrome")
    assert calls is not None and calls[0].name == "open_app"
    calls = router.match_tier0("abre o youtube")
    assert calls is not None and calls[0].arguments == {"url": "youtube.com"}
    catalog = CommandCatalog.build(router.match_tier0, ["Chrome"], site_phrases())
    assert "Abra o YouTube." in {c.phrase for c in catalog.candidates}


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("Pesquise, Zevaqueiro, Flash e coloque no YouTube para tocar.", "Zevaqueiro Flash"),
        ("toca Bohemian Rhapsody no YouTube", "Bohemian Rhapsody"),
        ("Shiro, coloca a música do Matuê no YouTube", "Matuê"),
    ],
)
def test_play_on_youtube(text: str, query: str) -> None:
    assert RULES(text) == [("open_url", {"search": query, "on": "youtube", "play": True})]


PROGRAMS = ["Claude", "Calculadora", "Bloco de Notas", "Google Chrome", "Epic Games Launcher"]
WINDOWS = ["Claude", "Wikipedia - Google Chrome"]


def _programs_rules() -> object:
    from shiro.application.control.rules import ProgramRules
    from shiro.infrastructure.tools.programs import spoken_to_name

    return ProgramRules(
        program=lambda s: spoken_to_name(s, PROGRAMS), window=lambda s: spoken_to_name(s, WINDOWS)
    )


@pytest.mark.parametrize(
    ("text", "call"),
    [
        ("Abra a janela do Claude.", ("switch_window", {"name": "claude"})),
        ("vai pro chrome", ("switch_window", {"name": "chrome"})),
        ("abre a calculadora", ("open_program", {"name": "calculadora"})),
        ("Shiro, abre o notepad", ("open_program", {"name": "notepad"})),
        ("inicia o epic games", ("open_program", {"name": "epic games"})),
    ],
)
def test_programs_and_windows(text: str, call: tuple[str, dict[str, object]]) -> None:
    rules = _programs_rules()
    assert rules(text) == [call]  # type: ignore[operator]


@pytest.mark.parametrize("text", ["abre a pasta downloads", "vai pra cama", "abre o jogo xyzzy"])
def test_unknown_programs_go_to_the_model(text: str) -> None:
    assert _programs_rules()(text) is None  # type: ignore[operator]


def test_launcher_prefix_is_ignored() -> None:
    from shiro.application.control.rules import ProgramRules
    from shiro.infrastructure.tools.programs import spoken_to_name

    rules = ProgramRules(
        program=lambda s: spoken_to_name(s, ["Half-Life", "Steam"]), window=lambda s: None
    )
    assert rules("Na Steam, abra Half-Life.") == [("open_program", {"name": "half life"})]


def test_dictation_rule_and_spoken_punctuation() -> None:
    from shiro.application.control.rules import dictation_rule
    from shiro.application.voice.dictation import is_stop, spoken_punctuation

    for text in ("Shiro, modo ditado.", "liga o ditado", "vou ditar", "ditado"):
        assert dictation_rule(text) == [("start_dictation", {})], text
    assert dictation_rule("o ditado de ontem foi difícil") is None
    assert spoken_punctuation("oi vírgula tudo bem interrogação nova linha tchau ponto final") == (
        "oi, tudo bem?\ntchau."
    )
    assert spoken_punctuation("soma abre parênteses a vírgula b fecha parênteses") == "soma (a, b)"
    assert is_stop("Parar ditado.") and is_stop("Shiro, para o ditado") and not is_stop("ditado")
