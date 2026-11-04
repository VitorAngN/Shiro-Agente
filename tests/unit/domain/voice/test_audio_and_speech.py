"""Áudio (WAV, mono, tons) e texto falado (frases, transcrição limpa, sim ou não)."""

from __future__ import annotations

import numpy as np
import pytest

from shiro.domain.voice.audio import STT_RATE, Audio, Cues, concat, tone
from shiro.domain.voice.speech import clean_transcript, for_speech, sentences, yes_or_no


def test_wav_round_trip_and_resampling() -> None:
    clip = tone(440, 500, rate=24_000, volume=0.5)
    back = Audio.from_wav(clip.to_wav())
    assert back.rate == 24_000
    assert np.allclose(back.samples, clip.samples, atol=1e-4)
    assert clip.duration == pytest.approx(0.5)
    resampled = clip.resampled(STT_RATE)
    assert len(resampled.samples) == 8000
    assert resampled.resampled(STT_RATE) is not None
    assert Audio.empty().resampled(8000).duration == 0


def test_stereo_pcm_becomes_mono_and_cues_can_be_silenced() -> None:
    stereo = np.array([1000, 3000, -2000, -4000], dtype="<i2").tobytes()
    mono = Audio.from_pcm16(stereo, 8000, channels=2)
    assert np.allclose(mono.samples, [2000 / 32768, -3000 / 32768])
    quiet = Cues.generate(0)
    assert quiet.listening.duration == 0
    loud = Cues.generate(0.2)
    assert 0.15 < loud.listening.duration < 0.3
    assert float(np.abs(loud.listening.samples).max()) <= 0.2 + 1e-6
    assert concat([], 16000).duration == 0


def test_tone_has_no_click_at_the_edges() -> None:
    beep = tone(1000, 100, rate=16_000, volume=1.0)
    assert abs(float(beep.samples[0])) < 1e-3
    assert abs(float(beep.samples[-1])) < 0.01
    assert float(np.abs(beep.samples).max()) > 0.9


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("Anotado: prova, sexta, às 23h59.", "Anotado: prova, sexta, às 23 e 59."),
        ("Te lembro às 8h.", "Te lembro às 8 horas."),
        ("Às 1h da manhã.", "Às 1 hora da manhã."),
        ("Volume em 20%.", "Volume em 20 por cento."),
        ("Faz 21 °C em Curitiba.", "Faz 21 graus em Curitiba."),
        ("Custa R$ 10,50.", "Custa 10,50 reais."),
        ("**Pronto**: `ok`", "Pronto : ok"),
        ("Veja https://exemplo.com/x agora.", "Veja o link na tela agora."),
    ],
)
def test_for_speech(written: str, spoken: str) -> None:
    assert for_speech(written) == spoken


def test_sentences_keep_short_ones_together() -> None:
    assert sentences("Anotado: trabalho de cálculo, sexta. Te aviso um dia antes. Ok.") == [
        "Anotado: trabalho de cálculo, sexta.",
        "Te aviso um dia antes. Ok.",
    ]
    assert sentences("") == []
    assert sentences("Oi. Tudo certo por aqui, e com você?") == [
        "Oi. Tudo certo por aqui, e com você?"
    ]


@pytest.mark.parametrize(
    ("heard", "kept"),
    [
        ("Legendas pela comunidade Amara.org", ""),
        ("Obrigado.", ""),
        ("  ", ""),
        ("Obrigado por assistir!", ""),
        ("Abre o Spotify.", "Abre o Spotify."),
        ("obrigado pela ajuda", "obrigado pela ajuda"),
    ],
)
def test_clean_transcript_drops_known_hallucinations(heard: str, kept: str) -> None:
    assert clean_transcript(heard) == kept


@pytest.mark.parametrize(
    ("heard", "answer"),
    [
        ("Sim.", True),
        ("Pode sim, Shiro", True),
        ("Shiro, confirmo", True),
        ("Manda ver!", True),
        ("Não.", False),
        ("Não, deixa pra lá", False),
        ("Cancela", False),
        ("Melhor não", False),
        ("Talvez depois", None),
        ("Qual volume?", None),
    ],
)
def test_yes_or_no(heard: str, answer: bool | None) -> None:
    assert yes_or_no(heard) is answer
