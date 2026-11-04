"""Texto normalizado, números falados e ids ordenados no tempo."""

from __future__ import annotations

import re

import pytest

from shiro.domain.ids import uuid7
from shiro.domain.text import normalize, parse_number, similarity, sound_key


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


def test_uuid7_is_versioned_and_time_ordered() -> None:
    first, second = uuid7(), uuid7()
    pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    assert re.match(pattern, first)
    assert first[:13] <= second[:13]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Chrome", "crome"),
        ("Steam", "istim"),
        ("Steam", "stin"),
        ("WhatsApp", "uatsap"),
        ("Discord", "discórdia"),
    ],
)
def test_sound_key_matches_portuguese_pronunciation(a: str, b: str) -> None:
    assert sound_key(a) == sound_key(b)


def test_similarity() -> None:
    assert similarity("abc", "abc") == 1.0 and similarity("", "abc") == 0.0
    assert similarity("kron", "kroma") == 0.6
    assert sound_key("Einstein") != sound_key("Steam")
