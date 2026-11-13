"""Comandos shiro voice que não dependem de microfone nem alto-falante."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from shiro.config.settings import Settings
from shiro.domain.voice.audio import Audio
from shiro.interfaces.cli import voice as cli_voice
from shiro.interfaces.cli.main import main
from tests.fakes.voice import FakeSTT, FakeTTS


@pytest.fixture
def fake_voice(monkeypatch: pytest.MonkeyPatch) -> FakeTTS:
    tts = FakeTTS()
    monkeypatch.setattr(cli_voice, "_tts", lambda settings, engine=None: (tts, "voz: dublê"))
    return tts


async def test_say_writes_wav(tmp_path: Path, fake_voice: FakeTTS) -> None:
    out = tmp_path / "fala.wav"
    args = argparse.Namespace(text="Às 23h59.", out=out, engine=None)

    assert await cli_voice._say(Settings(), args) == 0  # pyright: ignore[reportPrivateUsage]

    assert fake_voice.spoken == ["Às 23 e 59."]
    assert Audio.from_wav(out.read_bytes()).rate == 24_000


async def test_bench_scores_transcripts_by_command(
    tmp_path: Path, fake_voice: FakeTTS, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard: list[str] = list(cli_voice.BENCH_PHRASES)
    heard[0] = "abaixa o volume pra trinta"  # comando diferente: conta como erro

    async def fake_stt(settings: Settings, model: str | None = None, **_: object) -> FakeSTT:
        stt = FakeSTT(list(heard))
        stt.name = f"dublê/{model}"  # type: ignore[attr-defined]
        return stt

    monkeypatch.setattr(cli_voice, "_ready_stt", fake_stt)
    out = tmp_path / "bench.json"
    args = argparse.Namespace(engine=["kokoro"], stt=["base"], out=out)

    assert await cli_voice._bench(Settings(), args) == 0  # pyright: ignore[reportPrivateUsage]

    report = json.loads(out.read_text(encoding="utf-8"))
    rows = report["stt"][0]["rows"]
    assert len(rows) == len(cli_voice.BENCH_PHRASES)
    assert [r["intent_ok"] for r in rows].count(False) == 1
    assert rows[0]["wer"] > 0
    assert report["tts"]["kokoro"]["rtf"] >= 0


async def test_bench_compares_with_and_without_command_correction(
    tmp_path: Path, fake_voice: FakeTTS, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard: list[str] = list(cli_voice.BENCH_PHRASES)
    target = heard.index("pula essa música")
    heard[target] = "Ula essa música."  # o começo da fala sumiu

    async def fake_stt(settings: Settings, model: str | None = None, **_: object) -> FakeSTT:
        scores = {"Ula essa música.": -0.4, "Pula essa música.": -0.9}
        return FakeSTT(list(heard) * 2, scores=scores)

    monkeypatch.setattr(cli_voice, "_ready_stt", fake_stt)
    out = tmp_path / "bench.json"
    args = argparse.Namespace(engine=["kokoro"], stt=["base"], out=out, commands="both")

    assert await cli_voice._bench(Settings(), args) == 0  # pyright: ignore[reportPrivateUsage]

    runs = json.loads(out.read_text(encoding="utf-8"))["stt"]
    assert [run["commands"] for run in runs] == [False, True]
    plain, corrected = runs[0]["rows"][target], runs[1]["rows"][target]
    assert not plain["intent_ok"] and "scores" not in plain
    assert corrected["intent_ok"] and corrected["heard"] == "Pula essa música."
    assert corrected["scores"]["free"] == "Ula essa música." and corrected["scores"]["corrected"]


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows há áudio e SAPI")
def test_voice_commands_explain_missing_audio(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHIRO_VOICE__TTS__ENGINE", "kokoro")  # a voz local, sem rede
    assert main(["voice", "say", "oi", "--out", str(tmp_path / "x.wav")]) == 1
    assert "shiro voice setup" in capsys.readouterr().out
    assert main(["voice", "devices"]) in (0, 1)  # sem PortAudio: explica e sai com 1


async def test_mic_test_compares_capture_modes_and_recommends_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    from shiro.application.voice import listening
    from shiro.infrastructure.voice import devices, silero

    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path))
    rate = 16_000
    voice = (0.3 * np.sin(np.arange(rate) / rate * 2 * np.pi * 220)).astype(np.float32)
    room = (0.003 * np.random.default_rng(1).standard_normal(rate // 3)).astype(np.float32)
    gated = Audio(np.concatenate([np.zeros(rate // 3, dtype=np.float32), voice]), rate)
    clean = Audio(np.concatenate([room, voice]), rate)

    async def fake_record(microphone: Any, *_: object) -> Audio | None:
        mode = microphone._capture  # pyright: ignore[reportPrivateUsage]
        if mode == "exclusive":
            raise devices.AudioDeviceError("outro app está usando o microfone")
        return {"mme": gated, "raw": clean}.get(mode)

    class Silent:
        def __init__(self, *_: object) -> None: ...

        async def play(self, audio: Audio) -> bool:
            return True

    monkeypatch.setattr(listening, "record_utterance", fake_record)
    monkeypatch.setattr(devices, "SoundDevicePlayer", Silent)
    monkeypatch.setattr(silero, "SileroVAD", Silent)
    monkeypatch.setattr(
        cli_voice, "_ready_stt", lambda *_a, **_k: _async(FakeSTT(["Abra o Spotify."] * 4))
    )
    args = argparse.Namespace(capture=None, mic=None, no_stt=False)

    assert await cli_voice._mic_test(Settings(), args) == 0  # pyright: ignore[reportPrivateUsage]

    out = capsys.readouterr().out
    assert "[mme]" in out and "corta o começo da fala" in out
    assert "não abriu: outro app" in out and "não ouvi nada" in out  # exclusive e wasapi
    assert 'capture = "raw"' in out
    manifests = list((tmp_path / "voice-samples").glob("*-mic-test/frases.json"))
    saved = json.loads(manifests[0].read_text("utf-8"))
    assert [item["capture"] for item in saved] == ["mme", "raw"]
    assert len(cli_voice.load_samples(str(manifests[0].parent))) == 2  # o bench lê de volta


def test_capture_verdicts() -> None:
    from shiro.domain.voice.diagnostics import MicReport

    cut = MicReport(0.95, 400.0, 0.3)
    clean = MicReport(0.0, 3.0, 0.3)
    verdict = cli_voice._capture_verdict  # pyright: ignore[reportPrivateUsage]
    assert "Nenhum modo" in verdict({}, "mme")
    assert "nada a mudar" in verdict({"mme": clean}, "mme")
    assert "antes do Windows" in verdict({"mme": cut, "raw": cut}, "mme")


def test_cli_offers_the_same_capture_modes_as_the_microphone() -> None:
    from shiro.infrastructure.voice.devices import CAPTURE_MODES

    assert CAPTURE_MODES == cli_voice.CAPTURE_CHOICES


async def _async(value: Any) -> Any:
    return value
