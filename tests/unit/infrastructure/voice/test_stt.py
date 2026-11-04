"""Whisper: filtra ruído, carrega uma vez e recebe o vocabulário."""

from __future__ import annotations

import pytest

from shiro.config.settings import STTSettings
from shiro.domain.voice.audio import tone
from shiro.infrastructure.voice.stt import FasterWhisperSTT, vocabulary_hotwords, vocabulary_prompt
from tests.fakes.voice import FakeWhisper, segment


async def test_whisper_filters_noise_and_loads_once() -> None:
    model = FakeWhisper([segment(" Abre o"), segment(" Spotify."), segment(" la", 0.9, -1.5)])
    created: list[str] = []

    def factory(settings: STTSettings, source: str) -> FakeWhisper:
        created.append(source)
        return model

    stt = FasterWhisperSTT(
        STTSettings(model="base"), source="/modelos/base", prompt="Shiro.", factory=factory
    )
    clip = tone(300, 1000, rate=24_000)
    first = await stt.transcribe(clip)
    await stt.transcribe(clip)

    assert first.text == "Abre o Spotify."
    assert first.audio_s == pytest.approx(1.0)
    assert created == ["/modelos/base"]
    call = model.calls[0]
    assert call["samples"] == 16_000  # reamostrado para 16 kHz
    assert (call["language"], call["beam_size"], call["initial_prompt"]) == ("pt", 1, "Shiro.")
    assert stt.name == "faster-whisper/base"

    silent = FasterWhisperSTT(
        STTSettings(), factory=lambda _, __: FakeWhisper([segment("Obrigado.")])
    )
    assert (await silent.transcribe(clip)).text == ""


def test_vocabulary_prompt_names_the_assistant_and_apps() -> None:
    prompt = vocabulary_prompt("Shiro", ["Spotify", "VS Code"])
    assert prompt.startswith("Shiro, que horas são?")
    assert "Abra o Spotify." in prompt and "Abra o VS Code." in prompt  # comandos de exemplo
    assert vocabulary_prompt("Shiro", []).startswith("Shiro,")
    assert vocabulary_hotwords("Shiro", ["Steam", "Chrome"]) == "Shiro Steam Chrome"
