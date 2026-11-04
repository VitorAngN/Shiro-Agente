"""Reconhecer "Ei, Shiro" do jeito que o Whisper escreve."""

from __future__ import annotations

import pytest

from shiro.domain.voice.wake_phrase import strip_wake, wake_match

PHRASES = ("ei shiro", "oi shiro", "ok shiro", "hey shiro", "shiro")


@pytest.mark.parametrize(
    ("heard", "rest"),
    [
        ("Ei, Shiro!", ""),
        ("Shiro.", ""),
        ("Ei Xiro, abre o Spotify.", "abre o spotify"),
        ("Oi, Chiro, que horas são?", "que horas sao"),
        ("Hum, ei Shiro, pausa a música", "pausa a musica"),
        ("Ok Shiro", ""),
        # como o Whisper escreve o chamado (medido no PC de referência)
        ("Aiciro.", ""),
        ("Aiciru.", ""),
        ("Aishiro, abre o Spotify.", "abre o spotify"),
        ("Eishiro, abre o Spotify.", "abre o spotify"),
        ("A. Shiro.", ""),
        ("E Shiro, abre o Spotify.", "abre o spotify"),
        ("A Shiro é legal", None),  # artigo sem vírgula: falando dela, não com ela
        ("Ciro, me passa o sal", None),
        ("O Shiro é legal", None),  # o nome no meio de uma conversa não ativa
        ("Eu falei com a Shiro ontem", None),
        ("Abre o Spotify", None),
        ("", None),
    ],
)
def test_wake_match(heard: str, rest: str | None) -> None:
    assert wake_match(heard, PHRASES) == rest


def test_strip_wake_keeps_accents_of_the_request() -> None:
    assert strip_wake("Ei, Shiro, que horas são?", PHRASES) == "que horas são?"
    assert strip_wake("Shiro abre o VS Code", PHRASES) == "abre o VS Code"
    assert strip_wake("abre o Spotify", PHRASES) == "abre o Spotify"
    assert strip_wake("E Shiro, abre o Spotify.", PHRASES) == "abre o Spotify."
    assert strip_wake("Aishiro, pausa a música", PHRASES) == "pausa a música"
    assert wake_match("Ei Kira, abre o Spotify", ("ei kira",)) == "abre o spotify"
