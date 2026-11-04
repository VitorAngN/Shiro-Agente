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


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> str:
    pytest.importorskip("ctranslate2")
    from tests.fakes.tiny_whisper import build_tiny_whisper

    return str(build_tiny_whisper(tmp_path_factory.mktemp("whisper") / "tiny"))


async def test_phrases_are_scored_by_the_real_decoder_in_batches(tiny_model: str) -> None:
    stt = FasterWhisperSTT(
        STTSettings(), source=tiny_model, prompt="Shiro, que horas são?", hotwords="Shiro Steam"
    )
    clip = tone(300, 1500, rate=24_000)
    phrases = ["Abra o Steam.", "Feche o Chrome.", "Pausa a música."] * 7  # 21: dois lotes
    scores = await stt.score(clip, phrases)

    assert len(scores) == len(phrases)
    assert all(-30 < s < 0 for s in scores)
    assert scores[0] == pytest.approx(scores[3]) == pytest.approx(scores[18])  # mesma frase
    assert len({round(s, 6) for s in scores[:3]}) == 3  # frases diferentes, notas diferentes
    assert await stt.score(clip, []) == []

    plain = FasterWhisperSTT(STTSettings(), source=tiny_model)
    assert len(await plain.score(clip, ["Que horas são?"])) == 1  # sem prompt também funciona
