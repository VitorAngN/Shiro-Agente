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
