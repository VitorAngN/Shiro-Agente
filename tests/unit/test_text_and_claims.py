from __future__ import annotations

import re

import pytest

from shiro.core.claims import claims_action
from shiro.core.ids import uuid7
from shiro.core.text import normalize, parse_number


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("20", 20),
        ("vinte", 20),
        ("trinta e cinco", 35),
        ("cem", 100),
        ("zero", 0),
        ("quinze", 15),
        ("50%", 50),
        ("sessenta por cento", 60),
        ("vinte e dez", None),
        ("muito", None),
        ("", None),
    ],
)
def test_parse_number(spoken: str, expected: int | None) -> None:
    assert parse_number(spoken) == expected


def test_normalize_removes_accents_and_punctuation() -> None:
    assert (
        normalize("  Ei, SHIRO! Abaixa o VOLUME pra 20%.  ") == "ei shiro abaixa o volume pra 20%"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Entendido! Marquei sua atividade como concluída.",  # caso real do benchmark
        "Pronto! Volume em 20.",
        "Feito.",
        "Abri o Spotify para você.",
        "Sua atividade já está marcada.",
        "Criei o lembrete para as 20h.",
    ],
)
def test_detects_claimed_actions(text: str) -> None:
    assert claims_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "Qual app você quer que eu feche?",
        "Qual atividade devo marcar como concluída?",
        "15% de 340 é 51.",
        "Não posso apagar pastas do sistema.",
        "Não consegui abrir o Spotify.",
        "Não abri o app porque ele não está na lista.",
        "Estou pronto para ajudar.",
        "Ainda não consigo marcar atividades.",
        "Agora são 17h05.",
        "",
    ],
)
def test_ignores_questions_negations_and_plain_answers(text: str) -> None:
    assert not claims_action(text)


def test_uuid7_is_versioned_and_time_ordered() -> None:
    first, second = uuid7(), uuid7()
    pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(pattern, first)
    assert first[:13] <= second[:13]
