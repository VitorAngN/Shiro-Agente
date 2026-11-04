"""Palavra de ativação: ouvinte com Whisper e com openWakeWord."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from shiro.domain.voice.audio import Audio
from shiro.domain.voice.endpointing import EndpointConfig
from shiro.domain.voice.ports import Transcript
from shiro.infrastructure.voice import models
from shiro.infrastructure.voice.wake import WakeListener
from tests.fakes.voice import FakeMic, ScriptedDetector, frames, utterance

PHRASES = ("ei shiro", "oi shiro", "ok shiro", "hey shiro", "shiro")


class Events:
    def __init__(self) -> None:
        self.got: list[str] = []

    def wake(self) -> None:
        self.got.append("wake")

    def command(self, text: str) -> None:
        self.got.append(f"command:{text}")


class SequenceSTT:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    async def load(self) -> None:
        return None

    async def transcribe(self, audio: Audio) -> Transcript:
        self.calls += 1
        return Transcript(self.texts.pop(0) if self.texts else "", audio.duration, 1)


async def test_whisper_wake_listener() -> None:
    blocks = utterance() + utterance() + utterance() + utterance(300)
    check = SequenceSTT(["Ei, Shiro", "conversa qualquer", "Ei Shiro, abre o Spotify"])
    full = SequenceSTT(["Ei Shiro, abre o Spotify."])
    events = Events()
    listener = WakeListener(
        microphone=FakeMic(blocks), events=events, is_idle=lambda: True, cooldown_s=0
    )

    await listener.run_whisper(
        vad=ScriptedDetector(),
        check=check,
        full=full,
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320, max_utterance_s=15),
        max_phrase_s=3.0,
    )

    assert events.got == ["wake", "command:abre o Spotify."]
    assert check.calls == 3  # a fala longa (9,6 s > 3 s) nem foi transcrita
    assert full.calls == 1


async def test_wake_is_ignored_while_busy_or_disabled() -> None:
    events = Events()
    busy = WakeListener(microphone=FakeMic(utterance()), events=events, is_idle=lambda: False)
    await busy.run_whisper(
        vad=ScriptedDetector(),
        check=SequenceSTT(["Ei Shiro"]),
        full=SequenceSTT([]),
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320),
        max_phrase_s=8,
    )
    off = WakeListener(microphone=FakeMic(utterance()), events=events, is_idle=lambda: True)
    off.enabled = False
    await off.run_whisper(
        vad=ScriptedDetector(),
        check=SequenceSTT(["Ei Shiro"]),
        full=SequenceSTT([]),
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320),
        max_phrase_s=8,
    )
    assert events.got == []


class ScriptedWakeModel:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.resets = 0

    def score(self, chunk: np.ndarray) -> float:
        assert chunk.dtype == np.int16 and chunk.shape == (1280,)
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        self.resets += 1


async def test_openwakeword_listener_fires_once_per_cooldown() -> None:
    model = ScriptedWakeModel([0.1, 0.9, 0.95, 0.2, 0.1])
    events = Events()
    blocks = frames(13)  # 13 x 512 = 6656 amostras = 5 blocos de 1280
    listener = WakeListener(microphone=FakeMic(blocks), events=events, is_idle=lambda: True)
    await listener.run_openwakeword(model, threshold=0.5)  # type: ignore[arg-type]
    assert events.got == ["wake"]  # o segundo pico cai no tempo de espera
    assert model.resets == 1


async def test_openwakeword_files_are_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"onnx"
    for name in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        monkeypatch.setitem(models.KNOWN_SHA256, name, hashlib.sha256(body).hexdigest())
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    files = await models.ensure_openwakeword(client, tmp_path, "hey_jarvis")
    assert files.wakeword.name == "hey_jarvis_v0.1.onnx" and files.melspectrogram.is_file()

    custom = tmp_path / "ei_shiro.onnx"
    custom.write_bytes(b"x")
    assert (await models.ensure_openwakeword(client, tmp_path, str(custom))).wakeword == custom
    with pytest.raises(models.DownloadError, match="não encontrado"):
        await models.ensure_openwakeword(client, tmp_path, str(tmp_path / "nada.onnx"))
    await client.aclose()


class FakeOnnx:
    """Sessão ONNX de mentira que confere os formatos que o openWakeWord espera."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "x", "shape": [1, 16, 96]})()]

    def run(self, _: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.calls += 1
        (value,) = feed.values()
        if self.kind == "mel":
            assert value.ndim == 2 and value.dtype == np.float32
            frames_out = max(1, (value.shape[1] - 400) // 160)
            return [np.zeros((1, 1, frames_out, 32), dtype=np.float32)]
        if self.kind == "embedding":
            assert value.shape[1:] == (76, 32, 1)
            return [np.ones((value.shape[0], 1, 1, 96), dtype=np.float32)]
        assert value.shape == (1, 16, 96)
        return [np.array([[0.75]], dtype=np.float32)]


def test_openwakeword_pipeline_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    from shiro.infrastructure.voice import oww

    kinds = iter(["mel", "embedding", "wake"])
    monkeypatch.setattr(oww, "_session", lambda path: FakeOnnx(next(kinds)))
    detector = oww.OpenWakeWord(melspectrogram=Path("m"), embedding=Path("e"), wakeword=Path("w"))
    chunk = np.zeros(oww.CHUNK, dtype=np.int16)
    scores = [detector.score(chunk) for _ in range(7)]
    assert scores[:5] == [0.0] * 5  # aquecimento, como no openWakeWord
    assert scores[5:] == [0.75, 0.75]
    with pytest.raises(ValueError, match="1280"):
        detector.score(np.zeros(100, dtype=np.int16))
