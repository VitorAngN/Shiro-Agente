"""Endpointer: início, pausas curtas, fim da frase e pré-roll no buffer circular."""

from __future__ import annotations

import numpy as np

from shiro.domain.voice.endpointing import FRAME, EndpointConfig, Endpointer, Status
from tests.fakes.voice import push_all


def test_endpointer_detects_start_and_end_with_pre_roll() -> None:
    config = EndpointConfig(end_silence_ms=320, pre_roll_ms=64, start_frames=3)
    endpointer = Endpointer(config)
    # 5 quadros de silêncio, 20 de fala, 12 de silêncio (384 ms > 320 ms)
    status = push_all(endpointer, [0.0] * 5 + [0.9] * 20 + [0.0] * 12)

    assert status is Status.DONE
    audio = endpointer.audio()
    first = int(audio.samples[0])
    assert first == 3  # 2 quadros de pré-escuta antes dos 3 que confirmaram a fala
    # termina com só 3 quadros de silêncio depois da fala
    assert int(audio.samples[-1]) == 5 + 20 + 2


def test_short_pauses_do_not_end_the_phrase() -> None:
    endpointer = Endpointer(EndpointConfig(end_silence_ms=320))
    pattern = [0.9] * 5 + ([0.1] * 6 + [0.9] * 3) * 4  # pausas de 192 ms
    assert push_all(endpointer, pattern) is Status.SPEAKING
    # 0.4 está na histerese (limiar 0.5 - 0.15 = 0.35): não conta como silêncio
    assert push_all(endpointer, [0.4] * 30) is Status.SPEAKING


def test_no_speech_times_out_and_long_speech_is_cut() -> None:
    quiet = Endpointer(EndpointConfig(start_timeout_s=1.0))
    assert push_all(quiet, [0.2] * 40) is Status.NO_SPEECH  # 40 x 32 ms > 1 s
    assert quiet.push(np.zeros(FRAME, dtype=np.float32), 0.9) is Status.NO_SPEECH

    chatty = Endpointer(EndpointConfig(max_utterance_s=2.0))
    assert push_all(chatty, [0.9] * 80) is Status.DONE
    assert chatty.audio().duration <= 2.2
