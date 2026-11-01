"""Tier 0 de atividades e lembretes (ADR-0014): frases fixas, sem LLM."""

from __future__ import annotations

from datetime import datetime

import pytest

from shiro.activities.rules import ActivityRules
from shiro.core.router import IntentRouter
from tests.fakes import SAO_PAULO

WEDNESDAY = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
rules = ActivityRules(lambda: WEDNESDAY)


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        (
            "tenho prova de física dia 12 às 19h",
            ("create_activity", {"title": "prova de física", "due_text": "dia 12 às 19h"}),
        ),
        (
            "Ei Shiro, tenho uma reunião com o grupo amanhã à tarde",
            ("create_activity", {"title": "reunião com o grupo", "due_text": "amanhã à tarde"}),
        ),
        (
            "tenho que entregar o relatório sexta",
            ("create_activity", {"title": "entregar o relatório", "due_text": "sexta"}),
        ),
        (
            "anota que eu preciso comprar café",
            ("create_activity", {"title": "comprar café"}),
        ),
        (
            "A nota que eu preciso comprar café.",  # como o Whisper às vezes transcreve
            ("create_activity", {"title": "comprar café"}),
        ),
        (
            "anota aí o trabalho de cálculo pra sexta, por favor",
            ("create_activity", {"title": "trabalho de cálculo", "due_text": "pra sexta"}),
        ),
        (
            "me lembra de tirar a roupa do varal daqui a pouco, às seis",
            ("create_reminder", {"text": "tirar a roupa do varal", "when_text": "às seis"}),
        ),
        (
            "me lembra de entregar o relatório de física às oito da noite",
            (
                "create_reminder",
                {"text": "entregar o relatório de física", "when_text": "às oito da noite"},
            ),
        ),
        (
            "lembra de tirar o bolo do forno daqui a 40 minutos",
            (
                "create_reminder",
                {"text": "tirar o bolo do forno", "when_text": "daqui a 40 minutos"},
            ),
        ),
    ],
)
def test_common_phrases_become_tool_calls(
    spoken: str, expected: tuple[str, dict[str, object]]
) -> None:
    assert rules(spoken) == [expected]


@pytest.mark.parametrize(
    "spoken",
    [
        "tenho prova amanhã?",  # pergunta
        "tenho 20 anos",  # "tenho" sem algo com prazo
        "anota uma atividade",  # não diz o quê: a SHIRO pergunta
        "tenho prova de física",  # "tenho ..." exige prazo
        "tenho que dormir",  # idem
        "me lembra de pagar a conta",  # lembrete sem quando
        "anota amanhã prova de química",  # prazo no meio: o modelo decide
        "tenho prova sexta e trabalho segunda",  # dois prazos
        "preciso entregar o relatório sexta",  # "preciso" sozinho fica com o modelo
        "me lembra amanhã de manhã de ligar pro dentista",
    ],
)
def test_anything_else_goes_to_the_model(spoken: str) -> None:
    assert rules(spoken) is None


def test_router_tries_plugged_rules_after_its_own() -> None:
    router = IntentRouter(apps={}, cloud_triggers=(), rules=(rules,))

    noted = router.match_tier0("tenho prova de física dia 12")
    assert noted is not None
    assert noted[0].name == "create_activity"
    # "terminei ..." é regra embutida e vem antes
    done = router.match_tier0("já dei conta daquele relatório, pode tirar da lista")
    assert done is not None
    assert (done[0].name, done[0].arguments) == ("complete_activity", {"query": "relatorio"})
    fiz = router.match_tier0("já fiz a lista de cálculo")
    assert fiz is not None
    assert fiz[0].arguments == {"query": "a lista de calculo"}
    era = router.match_tier0("aquela prova de física já era, pode considerar feita")
    assert era is not None
    assert era[0].arguments == {"query": "prova de fisica"}
    pronto = router.match_tier0("o relatório tá pronto")
    assert pronto is not None
    assert pronto[0].arguments == {"query": "relatorio"}
    assert router.match_tier0("a festa já foi ótima") is None
    risca = router.match_tier0("pode riscar a prova de física, já fiz")
    assert risca is not None
    assert risca[0].arguments == {"query": "a prova de fisica"}
    baixa = router.match_tier0("dá baixa na lista de cálculo")
    assert baixa is not None
    assert baixa[0].arguments == {"query": "lista de calculo"}
    assert router.match_tier0("como vai você") is None
