"""Regra do reconhecimento restrito: só troca o texto quando um comando ganha com folga."""

from __future__ import annotations

from shiro.domain.voice.rescoring import Candidate, RescoreRule, Scored

PAUSE = Candidate("Pausa a música.", "pause")
PAUSE_TOO = Candidate("Pause a música.", "pause")
PLAY = Candidate("Toca a música.", "play")
STEAM = Candidate("Abra o Steam.", "open steam")

RULE = RescoreRule(slack=1.0, margin=0.3, floor=-2.5)


def test_clear_winner_close_to_the_free_transcript_is_chosen() -> None:
    scored = [Scored(PAUSE, -0.9), Scored(PLAY, -2.0), Scored(STEAM, -3.1)]
    choice = RULE.choose(-0.4, scored)
    assert choice is not None and choice.candidate is PAUSE


def test_free_speech_that_explains_the_audio_much_better_is_kept() -> None:
    # "me conta uma piada": nenhum comando chega perto da transcrição livre
    assert RULE.choose(-0.3, [Scored(PAUSE, -1.6), Scored(PLAY, -2.4)]) is None


def test_two_different_actions_too_close_is_doubt() -> None:
    assert RULE.choose(-0.5, [Scored(PAUSE, -0.9), Scored(PLAY, -1.1)]) is None


def test_variants_of_the_same_action_do_not_compete() -> None:
    scored = [Scored(PAUSE, -0.9), Scored(PAUSE_TOO, -0.95), Scored(PLAY, -1.6)]
    choice = RULE.choose(-0.5, scored)
    assert choice is not None and choice.candidate.action == "pause"


def test_below_the_floor_nothing_is_a_command() -> None:
    assert RULE.choose(-2.0, [Scored(PAUSE, -2.8), Scored(PLAY, -4.0)]) is None
    assert RULE.choose(-0.5, []) is None


def test_only_short_phrases_are_rescored() -> None:
    assert RULE.applies_to("Ausa música.")
    assert not RULE.applies_to("")
    assert not RULE.applies_to("me explica como funciona a fotossíntese nas plantas verdes")
