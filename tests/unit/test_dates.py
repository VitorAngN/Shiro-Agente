"""Tabela de prazos em pt-BR (RNF-16: ≥ 95% de datas corretas)."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from shiro.activities.dates import describe, ground, locate, resolve
from tests.fakes import SAO_PAULO

# Domingo, 1º de novembro de 2026, 4h da manhã.
SUNDAY = datetime(2026, 11, 1, 4, 0, tzinfo=SAO_PAULO)
# Quarta-feira, 4 de novembro de 2026, 10h.
WEDNESDAY = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)


def at(day: int, hour: int = 23, minute: int = 59, month: int = 11, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SAO_PAULO)


@pytest.mark.parametrize(
    ("spoken", "now", "expected"),
    [
        # dias da semana
        ("sexta", SUNDAY, at(6)),
        ("pra sexta", SUNDAY, at(6)),
        ("até sexta-feira", SUNDAY, at(6)),
        ("sexta", WEDNESDAY, at(6)),
        ("sexta que vem", WEDNESDAY, at(13)),
        ("próxima sexta", WEDNESDAY, at(13)),
        ("quarta", WEDNESDAY, at(4)),  # hoje, ainda dá tempo até 23h59
        ("segunda às 8h", SUNDAY, at(2, 8, 0)),
        ("segunda às 8 da manhã", SUNDAY, at(2, 8, 0)),
        ("quinta às 7 da noite", SUNDAY, at(5, 19, 0)),
        ("sexta ao meio-dia", SUNDAY, at(6, 12, 0)),
        ("sexta à meia-noite", SUNDAY, at(6, 23, 59)),
        ("domingo", SUNDAY, at(1)),
        # relativos
        ("hoje", SUNDAY, at(1)),
        ("amanhã", SUNDAY, at(2)),
        ("depois de amanhã", SUNDAY, at(3)),
        ("daqui a 3 dias", SUNDAY, at(4)),
        ("em duas semanas", SUNDAY, at(15)),
        ("daqui a uma semana", SUNDAY, at(8)),
        # dia do mês
        ("dia 12", SUNDAY, at(12)),
        ("dia 12 às 19h", SUNDAY, at(12, 19, 0)),
        ("dia 12 às 23h59", SUNDAY, at(12, 23, 59)),
        ("dia 1", SUNDAY, at(1)),
        ("dia 2", WEDNESDAY, at(2, month=12)),  # já passou neste mês
        ("dia 31", SUNDAY, at(31, month=12)),  # novembro não tem 31
        ("dia 5 do mês que vem", SUNDAY, at(5, month=12)),
        ("15 de dezembro", SUNDAY, at(15, month=12)),
        ("dia 5 de janeiro", SUNDAY, at(5, month=1, year=2027)),
        ("dia doze", SUNDAY, at(12)),
        # data numérica
        ("12/11", SUNDAY, at(12)),
        ("12/11 às 23h59", SUNDAY, at(12)),
        ("25/12", SUNDAY, at(25, month=12)),
        ("10/01", SUNDAY, at(10, month=1, year=2027)),
        ("10/01/2027 às 14h30", SUNDAY, at(10, 14, 30, month=1, year=2027)),
        # só horário
        ("às 20h", SUNDAY, at(1, 20, 0)),
        ("às oito da noite", SUNDAY, at(1, 20, 0)),
        ("às sete e meia da noite", SUNDAY, at(1, 19, 30)),
        ("19:30", SUNDAY, at(1, 19, 30)),
        ("às 3h", SUNDAY, at(2, 3, 0)),  # já passou hoje: amanhã
        ("hoje às 20h", SUNDAY, at(1, 20, 0)),
        ("amanhã às 7 e meia", SUNDAY, at(2, 7, 30)),
        # hora falada sem período: o próximo daquele número no relógio
        ("às seis", WEDNESDAY, at(4, 18, 0)),
        ("às 6", WEDNESDAY, at(4, 18, 0)),
        ("hoje às seis", WEDNESDAY, at(4, 18, 0)),
        ("às seis", SUNDAY, at(1, 6, 0)),  # 4h da manhã: ainda vem o das 6h
        ("às 6h", WEDNESDAY, at(5, 6, 0)),  # escrito com "h": literal
        ("amanhã às 8", WEDNESDAY, at(5, 8, 0)),  # outro dia: literal
        # relativo a agora
        ("daqui a 40 minutos", WEDNESDAY, at(4, 10, 40)),
        ("em 2 horas", WEDNESDAY, at(4, 12, 0)),
        ("daqui a meia hora", WEDNESDAY, at(4, 10, 30)),
        ("daqui a uma hora e meia", WEDNESDAY, at(4, 11, 30)),
        # partes do dia
        ("amanhã de manhã", SUNDAY, at(2, 9, 0)),
        ("sexta à tarde", SUNDAY, at(6, 14, 0)),
        ("hoje à noite", SUNDAY, at(1, 20, 0)),
    ],
)
def test_resolves_spoken_deadlines(spoken: str, now: datetime, expected: datetime) -> None:
    result = resolve(spoken, now=now)
    assert result.ok, result.problem
    assert result.when == expected


@pytest.mark.parametrize(
    ("spoken", "problem"),
    [
        ("semana que vem", "Qual dia da semana que vem?"),
        ("mês que vem", "Qual dia do mês que vem?"),
        ("qualquer dia", "Não entendi o prazo"),
        ("hoje às 3h", "já passou"),
        ("às 25h", "não existe"),
        ("31/02", "não existe"),
        ("31 de fevereiro", "Fevereiro não tem dia 31"),
    ],
)
def test_vague_or_impossible_deadlines_ask_instead_of_guessing(spoken: str, problem: str) -> None:
    result = resolve(spoken, now=SUNDAY)
    assert not result.ok
    assert result.problem is not None and problem in result.problem


def test_postpone_is_relative_to_the_current_deadline() -> None:
    current = at(12, 19, 0)
    assert resolve("semana que vem", now=SUNDAY, base=current).when == at(19, 19, 0)
    assert resolve("mês que vem", now=SUNDAY, base=current).when == at(12, 19, 0, month=12)
    assert resolve("sexta", now=SUNDAY, base=current).when == at(6, 19, 0)  # mantém o horário
    assert resolve("sexta às 10h", now=SUNDAY, base=current).when == at(6, 10, 0)


def test_empty_means_no_deadline_and_custom_default_time() -> None:
    assert resolve("", now=SUNDAY).when is None
    assert resolve(None, now=SUNDAY).ok
    reminder = resolve("amanhã", now=SUNDAY, default_time=time(9, 0))
    assert reminder.when == at(2, 9, 0)
    assert not reminder.has_time
    assert resolve("amanhã às 10h", now=SUNDAY).has_time


def test_describe_in_portuguese() -> None:
    assert describe(at(6), SUNDAY) == "sexta-feira, 6 de novembro, às 23h59"
    assert describe(at(1, 20, 0), SUNDAY) == "hoje, às 20h"
    assert describe(at(2, 7, 30), SUNDAY) == "amanhã, às 7h30"
    assert describe(at(5, 9, 0, month=1, year=2027), SUNDAY) == (
        "terça-feira, 5 de janeiro de 2027, às 9h"
    )


def test_duration_is_not_a_time() -> None:
    assert not resolve("2 horas", now=SUNDAY).understood
    assert resolve("às 2 horas", now=SUNDAY).when == at(1, 14, 0)


@pytest.mark.parametrize(
    ("utterance", "spans"),
    [
        ("tenho prova de cálculo amanhã às 8h", ["amanhã às 8h"]),
        ("me lembra de tirar a roupa do varal daqui a pouco, às seis", ["às seis"]),
        ("me lembra de tirar o bolo do forno daqui a 40 minutos", ["daqui a 40 minutos"]),
        ("adia o trabalho de sexta pra segunda", ["de sexta", "pra segunda"]),
        ("estudar 2 horas amanhã", ["amanhã"]),
        ("estudar o dia todo", []),
        ("comprar 5 pães", []),
    ],
)
def test_locate_finds_time_expressions_in_a_sentence(utterance: str, spans: list[str]) -> None:
    assert [s.text for s in locate(utterance, now=WEDNESDAY)] == spans


@pytest.mark.parametrize(
    ("spoken", "utterance", "exclude", "grounded"),
    [
        # cortou o dia: volta a expressão inteira
        ("às 8h", "tenho prova de cálculo amanhã às 8h", "", "amanhã às 8h"),
        # parafraseou: valem as palavras do usuário
        ("às 8h", "me lembra de ligar pra ela às oito da noite", "", "às oito da noite"),
        # omitiu o prazo: usa o único da frase, se não for parte do título
        (None, "tenho prova de física dia 12 às 19h", "prova de física", "dia 12 às 19h"),
        (None, "estudar pra prova de sexta", "estudar pra prova de sexta", None),
        # dia e hora separados na frase viram um prazo só
        ("às 10", "amanhã tenho prova de química às 10, anota aí", "", "amanhã às 10"),
        (None, "amanhã tenho prova de química às 10", "prova de química", "amanhã às 10"),
        # duas expressões: fica a que contém o que o modelo disse
        ("segunda", "adia o trabalho de sexta pra segunda", "", "pra segunda"),
        # duas expressões e nenhuma bate: fica o do modelo
        ("amanhã às 10h", "amanhã de manhã liga pro dentista às 10", "", "amanhã às 10h"),
        # sem expressão na fala: nada a ancorar
        ("sexta", "anota o trabalho", "", "sexta"),
        ("sexta", "", "", "sexta"),
    ],
)
def test_ground_prefers_the_users_words(
    spoken: str | None, utterance: str, exclude: str, grounded: str | None
) -> None:
    assert ground(spoken, utterance, now=WEDNESDAY, exclude=exclude) == grounded
