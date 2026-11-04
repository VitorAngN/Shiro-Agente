"""Comandos conhecidos na voz: o catálogo segue o roteador e a correção só age na dúvida."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from shiro.application.agent.router import IntentRouter
from shiro.application.voice.commands import CommandCatalog, CommandRescoringSTT
from shiro.domain.voice.audio import Audio, tone
from shiro.domain.voice.rescoring import RescoreRule
from tests.fakes.voice import FakeSTT

ROUTER = IntentRouter(
    apps={"steam": ["Steam"], "chrome": ["Chrome"], "vscode": ["VS Code", "code"]},
    cloud_triggers=[],
)
APPS = ["Steam", "Chrome", "VS Code"]
CLIP = tone(300, 800)


class TableScorer:
    """Notas fixas por frase; o que não está na tabela recebe ``default``."""

    def __init__(self, table: dict[str, float], default: float = -4.0) -> None:
        self.table = table
        self.default = default
        self.calls: list[list[str]] = []

    async def score(self, audio: Audio, phrases: Sequence[str]) -> list[float]:
        self.calls.append(list(phrases))
        return [self.table.get(phrase, self.default) for phrase in phrases]


def corrector(heard: str, table: dict[str, float]) -> tuple[CommandRescoringSTT, TableScorer]:
    scorer = TableScorer(table)
    stt = CommandRescoringSTT(
        FakeSTT([heard]),
        scorer=scorer,
        catalog=CommandCatalog.build(ROUTER.match_tier0, APPS),
        recognize=ROUTER.match_tier0,
        name="Shiro",
        rule=RescoreRule(slack=1.0, margin=0.3, floor=-2.5),
    )
    return stt, scorer


def test_every_catalog_phrase_is_understood_by_the_router() -> None:
    catalog = CommandCatalog.build(ROUTER.match_tier0, APPS)
    phrases = [c.phrase for c in catalog.candidates]
    assert "Abra o Steam." in phrases and "Fecha a VS Code." in phrases
    assert "Pausa a música." in phrases and "Volume em 30." in phrases
    assert "Que horas são?" in phrases
    for candidate in catalog.candidates:
        assert ROUTER.match_tier0(candidate.phrase), candidate.phrase
    actions = {c.phrase: c.action for c in catalog.candidates}
    assert actions["Abra o Steam."] == actions["Abre a Steam."] == "open_app(app=steam)"
    assert actions["Pausa a música."] == actions["Pause a música."] != actions["Toca a música."]
    assert actions["Que horas são?"] == actions["Que dia é hoje?"]


def test_apps_the_router_does_not_know_stay_out() -> None:
    catalog = CommandCatalog.build(ROUTER.match_tier0, ["Steam", "Photoshop"])
    assert not [c for c in catalog.candidates if "Photoshop" in c.phrase]


async def test_a_mangled_command_becomes_the_known_one() -> None:
    stt, scorer = corrector("Ausa música.", {"Ausa música.": -0.4, "Pausa a música.": -0.9})
    transcript = await stt.transcribe(CLIP)
    assert transcript.text == "Pausa a música."
    assert transcript.heard == "Ausa música."
    assert scorer.calls[0][0] == "Ausa música."  # a transcrição livre é medida junto
    assert stt.last is not None and stt.last.choice is not None
    assert stt.last.top(1)[0].candidate.phrase == "Pausa a música."


async def test_an_english_app_name_heard_as_another_word() -> None:
    stt, _ = corrector("Abra, Einstein.", {"Abra, Einstein.": -0.6, "Abra o Steam.": -1.2})
    assert (await stt.transcribe(CLIP)).text == "Abra o Steam."


async def test_commands_already_understood_are_not_rescored() -> None:
    stt, scorer = corrector("Abra o Chrome.", {})
    assert (await stt.transcribe(CLIP)).text == "Abra o Chrome."
    assert scorer.calls == [] and stt.last is None


async def test_long_or_empty_speech_is_left_alone() -> None:
    long_text = "me explica como funciona a fotossíntese nas plantas"
    stt, scorer = corrector(long_text, {})
    assert (await stt.transcribe(CLIP)).text == long_text
    stt, scorer = corrector("", {})
    assert (await stt.transcribe(CLIP)).text == ""
    assert scorer.calls == []


async def test_free_speech_wins_when_no_command_explains_the_audio() -> None:
    stt, _ = corrector("Me conta uma piada.", {"Me conta uma piada.": -0.3})
    transcript = await stt.transcribe(CLIP)
    assert transcript.text == "Me conta uma piada." and transcript.heard == ""
    assert stt.last is not None and stt.last.choice is None


async def test_speech_addressed_by_name_is_compared_with_addressed_commands() -> None:
    stt, scorer = corrector(
        "Shiro, ausa música.", {"Shiro, ausa música.": -0.5, "Shiro, pausa a música.": -0.8}
    )
    assert (await stt.transcribe(CLIP)).text == "Shiro, pausa a música."
    assert all(p.startswith("Shiro, ") for p in scorer.calls[0][1:])

    stt, scorer = corrector("Ei, Shiro, ausa música.", {"Ei, Shiro, pausa a música.": -0.8})
    assert (await stt.transcribe(CLIP)).text == "Ei, Shiro, pausa a música."  # palavra de ativação


async def test_wrapper_loads_the_inner_model_and_adds_the_scoring_time() -> None:
    stt, _ = corrector("Ausa música.", {"Ausa música.": -0.4, "Pausa a música.": -0.9})
    await stt.load()
    transcript = await stt.transcribe(CLIP)
    assert transcript.latency_ms >= 5  # 5 ms do Whisper de mentira + o tempo das notas
    assert stt.name.endswith("+ comandos")


@pytest.mark.parametrize("heard", ["Abra, Einstein.", "Ausa música."])
async def test_without_a_catalog_nothing_changes(heard: str) -> None:
    stt = CommandRescoringSTT(
        FakeSTT([heard]),
        scorer=TableScorer({}),
        catalog=CommandCatalog([]),
        recognize=ROUTER.match_tier0,
        name="Shiro",
    )
    assert (await stt.transcribe(CLIP)).text == heard
