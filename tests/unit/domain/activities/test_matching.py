"""Achar a atividade pelo nome falado e interpretar antecedências de aviso."""

from __future__ import annotations

from datetime import timedelta

from shiro.domain.activities import matching
from shiro.domain.activities.models import Activity, offset_phrase, parse_offset
from tests.fakes.clock import SUNDAY


def test_matching_and_offsets() -> None:
    now = SUNDAY
    items = [
        Activity(id="1", title="trabalho de cálculo", created_at=now, updated_at=now),
        Activity(
            id="2", title="prova de física", context="Física 3", created_at=now, updated_at=now
        ),
    ]
    assert [a.id for a in matching.find("o trabalho de calculo", items)] == ["1"]
    assert [a.id for a in matching.find("física 3", items)] == ["2"]
    assert matching.find("redação", items) == []
    assert matching.find("de", items) == []
    assert [a.id for a in matching.find("aquela prova de física", items)] == ["2"]

    assert parse_offset("1d") == timedelta(days=1)
    assert parse_offset("2h") == timedelta(hours=2)
    assert parse_offset("30m") == timedelta(minutes=30)
    assert offset_phrase(timedelta(days=1)) == "amanhã"
    assert offset_phrase(timedelta(hours=2)) == "em 2 horas"
    assert offset_phrase(timedelta(minutes=30)) == "em 30 minutos"
