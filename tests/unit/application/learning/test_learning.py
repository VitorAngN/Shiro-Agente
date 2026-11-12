"""Aprendizado (ADR-0023): ensinar uma expressão, usá-la e esquecê-la, com o roteador de verdade."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from shiro.application.agent.router import IntentRouter
from shiro.application.learning.rules import LearningRules
from shiro.application.learning.service import Lessons
from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.lessons import SqliteLessonStore
from tests.fakes.clock import MovableClock

RULES = LearningRules()


def calls(router: IntentRouter, text: str) -> list[tuple[str, dict[str, object]]] | None:
    found = router.match_tier0(text)
    return None if found is None else [(c.name, dict(c.arguments)) for c in found]


@pytest.fixture
async def setup() -> AsyncIterator[tuple[Lessons, IntentRouter, Database]]:
    database = await Database.open(":memory:")
    lessons = Lessons(SqliteLessonStore(database), MovableClock())
    await lessons.load()
    router = IntentRouter(
        apps={"steam": ["Steam"], "discord": ["Discord"]},
        cloud_triggers=[],
        teaching=(RULES,),
        expand=lessons.expand,
    )
    yield lessons, router, database
    await database.close()


@pytest.mark.parametrize(
    ("spoken", "trigger", "meaning"),
    [
        (
            "Quando eu disser modo jogo, feche o Discord e abra a Steam.",
            "modo jogo",
            "feche o discord e abra a steam",
        ),
        ("Shiro, quando eu falar “stim”, abra a Steam", "stim", "abra a steam"),
        ("sempre que eu pedir silêncio então pausa a música", "silencio", "pausa a musica"),
        ("Aprenda que stim é steam", "stim", "steam"),
        ("aprende que bora jogar significa abra a steam", "bora jogar", "abra a steam"),
    ],
)
def test_teaching_phrases(spoken: str, trigger: str, meaning: str) -> None:
    assert RULES(spoken) == [("learn_lesson", {"trigger": trigger, "meaning": meaning})]


def test_forgetting_listing_and_ordinary_speech() -> None:
    assert RULES("desaprende modo jogo") == [("forget_lesson", {"trigger": "modo jogo"})]
    assert RULES("Esquece o comando stim.") == [("forget_lesson", {"trigger": "stim"})]
    assert RULES("o que você aprendeu?") == [("list_lessons", {})]
    assert RULES("O que eu já te ensinei?") == [("list_lessons", {})]
    assert RULES("abra a steam") is None
    assert RULES("quando eu disser") is None
    assert RULES("esquece que eu gosto de café") is None  # isso é memória, não lição


async def test_a_taught_phrase_runs_the_commands_it_means(
    setup: tuple[Lessons, IntentRouter, Database],
) -> None:
    lessons, router, _ = setup
    assert calls(router, "modo jogo") is None
    taught = await lessons.learn("Modo Jogo", "feche o discord e abra a steam")
    assert taught.ok and "modo jogo" in taught.content

    expected = [("close_app", {"app": "discord"}), ("open_app", {"app": "steam"})]
    assert calls(router, "Modo jogo!") == expected
    assert calls(router, "Shiro, modo jogo por favor") == expected
    assert calls(router, "modo jogador") is None  # só a expressão inteira


async def test_a_taught_word_works_inside_other_requests(
    setup: tuple[Lessons, IntentRouter, Database],
) -> None:
    lessons, router, _ = setup
    await lessons.learn("stim", "steam")
    assert calls(router, "abra o stim") == [("open_app", {"app": "steam"})]
    assert router.rewrite("o stim tá em promoção?") == "o steam ta em promocao"
    assert router.rewrite("que horas são?") == "que horas são?"  # sem lição, texto intacto
    # ensinar ou desaprender usa a expressão crua
    assert calls(router, "desaprende stim") == [("forget_lesson", {"trigger": "stim"})]
    assert router.rewrite("desaprende stim") == "desaprende stim"


async def test_lessons_survive_a_restart_and_can_be_forgotten(
    setup: tuple[Lessons, IntentRouter, Database],
) -> None:
    lessons, router, database = setup
    await lessons.learn("modo jogo", "abra a steam")
    await lessons.learn("jogo", "abra o discord")

    again = Lessons(SqliteLessonStore(database), MovableClock())
    await again.load()
    assert [lesson.trigger for lesson in again.lessons()] == ["jogo", "modo jogo"]
    assert again.expand("modo jogo") == "abra a steam"  # a expressão mais longa ganha
    assert "2 expressões" in ((await again.list()).say or "")

    assert (await lessons.forget("Modo Jogo")).ok
    assert not (await lessons.forget("modo jogo")).ok
    assert calls(router, "jogo") == [("open_app", {"app": "discord"})]  # sobrou "jogo"
    await lessons.learn("jogo", "abra a steam")  # ensinar de novo substitui
    assert calls(router, "jogo") == [("open_app", {"app": "steam"})]


async def test_bad_lessons_are_refused(setup: tuple[Lessons, IntentRouter, Database]) -> None:
    lessons, _, _ = setup
    assert not (await lessons.learn("", "abra a steam")).ok
    assert not (await lessons.learn("um dois tres quatro cinco seis sete", "abra a steam")).ok
    assert not (await lessons.learn("jogo", "modo jogo agora")).ok  # se repetiria sem fim
    assert not (await lessons.learn("x", "a" * 201)).ok
    assert (await lessons.list()).say == "Você ainda não me ensinou nenhuma expressão."


def test_sequences_only_when_every_part_is_a_known_command() -> None:
    router = IntentRouter(apps={"steam": ["Steam"], "discord": ["Discord"]}, cloud_triggers=[])
    assert calls(router, "feche o discord e depois aumenta o volume") == [
        ("close_app", {"app": "discord"}),
        ("change_volume", {"delta": 10}),
    ]
    assert calls(router, "abra a steam e me conta uma piada") is None
