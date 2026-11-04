"""Comandos shiro voice que não dependem de microfone nem alto-falante."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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

    async def fake_stt(settings: Settings, model: str | None = None) -> FakeSTT:
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


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows há áudio e SAPI")
def test_voice_commands_explain_missing_audio(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path))
    assert main(["voice", "say", "oi", "--out", str(tmp_path / "x.wav")]) == 1
    assert "shiro voice setup" in capsys.readouterr().out
    assert main(["voice", "devices"]) in (0, 1)  # sem PortAudio: explica e sai com 1
