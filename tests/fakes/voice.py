"""Dublês de voz: microfone, detector de fala, Whisper, TTS, alto-falante e sessão."""

from __future__ import annotations

import asyncio
import contextlib
import io
from collections.abc import AsyncIterator, Callable, Sequence
from types import SimpleNamespace
from typing import Any

import numpy as np

from shiro.domain.models import AgentResult, DecisionKind, Tier
from shiro.domain.voice.audio import Audio, Cues, Samples, tone
from shiro.domain.voice.endpointing import FRAME, EndpointConfig, Endpointer, Status
from shiro.domain.voice.ports import Transcript
from shiro.interfaces.voice.session import (
    VoiceSession,
)


def frames(count: int, value: float = 0.0) -> list[Samples]:
    return [np.full(FRAME, value, dtype=np.float32) for _ in range(count)]


def push_all(endpointer: Endpointer, probabilities: list[float]) -> Status:
    status = endpointer.status
    for index, probability in enumerate(probabilities):
        status = endpointer.push(np.full(FRAME, index, dtype=np.float32), probability)
    return status


class FakeMic:
    def __init__(self, blocks: list[Samples]) -> None:
        self.blocks = blocks

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
        async def generate() -> AsyncIterator[Samples]:
            for block in self.blocks:
                await asyncio.sleep(0)
                yield block

        yield generate()


class ScriptedDetector:
    """Probabilidade = valor do primeiro elemento do quadro (os testes escrevem ali)."""

    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def probability(self, frame: Samples) -> float:
        return float(frame[0])


class FakeWhisper:
    def __init__(self, segments: list[SimpleNamespace]) -> None:
        self.segments = segments
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, samples: Samples, **options: Any) -> tuple[list[SimpleNamespace], None]:
        self.calls.append({"samples": len(samples), **options})
        return self.segments, None


def segment(text: str, no_speech: float = 0.1, logprob: float = -0.3) -> SimpleNamespace:
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


SPEECH = frames(3) + frames(10, 0.9) + frames(30)


class FakeSTT:
    """Whisper de mentira; ``scores`` dá a nota de frases para a correção de comandos."""

    def __init__(self, texts: list[str], scores: dict[str, float] | None = None) -> None:
        self.texts = texts
        self.scores = scores or {}
        self.heard: list[float] = []

    async def load(self) -> None:
        return None

    async def transcribe(self, audio: Audio) -> Transcript:
        self.heard.append(audio.duration)
        return Transcript(text=self.texts.pop(0) if self.texts else "", audio_s=1, latency_ms=5)

    async def score(self, audio: Audio, phrases: Sequence[str]) -> list[float]:
        # Sem nota na tabela, a transcrição livre (a primeira) explica o áudio muito melhor.
        return [self.scores.get(p, -0.2 if i == 0 else -6.0) for i, p in enumerate(phrases)]


class FakeTTS:
    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> Audio:
        self.spoken.append(text)
        await asyncio.sleep(0)
        return Audio(np.full(len(text), 0.5, dtype=np.float32), 24_000)

    async def aclose(self) -> None:
        return None


class FakePlayer:
    def __init__(self, interrupt_after: int | None = None) -> None:
        self.played: list[Audio] = []
        self.stopped = False
        self._interrupt_after = interrupt_after
        self.on_play: Callable[[], None] | None = None

    async def play(self, audio: Audio) -> bool:
        self.stopped = False
        self.played.append(audio)
        await asyncio.sleep(0)
        if self.on_play is not None:
            self.on_play()
        if self._interrupt_after is not None and len(self.played) >= self._interrupt_after:
            self.stopped = True
        return not self.stopped

    def stop(self) -> None:
        self.stopped = True


async def until(condition: Callable[[], bool], limit_s: float = 2.0) -> None:
    """Espera a sessão chegar a um estado (as tarefas dela rodam em paralelo)."""
    async with asyncio.timeout(limit_s):
        while not condition():  # noqa: ASYNC110 - estado da sessão, não um evento
            await asyncio.sleep(0.005)


CUES = Cues(listening=tone(880, 50), done=tone(740, 50), error=tone(300, 50))


def turn(text: str) -> AgentResult:
    return AgentResult(text=text, tier=Tier.T0, calls=(), steps=0)


def make_session(
    *,
    heard: list[str],
    reply: str = "Volume em 20%.",
    player: FakePlayer | None = None,
    mic_blocks: list[np.ndarray] | None = None,
) -> tuple[VoiceSession, FakeSTT, FakeTTS, FakePlayer, list[str], io.StringIO]:
    asked: list[str] = []

    async def run_turn(text: str) -> AgentResult:
        asked.append(text)
        await asyncio.sleep(0)
        return turn(reply)

    stt, tts, out = FakeSTT(heard), FakeTTS(), io.StringIO()
    player = player or FakePlayer()
    session = VoiceSession(
        run_turn=run_turn,
        stt=stt,
        tts=tts,
        player=player,
        microphone=FakeMic(mic_blocks if mic_blocks is not None else SPEECH),
        detector=ScriptedDetector(),
        listen=EndpointConfig(end_silence_ms=320),
        cues=CUES,
        name="Shiro",
        verbose=True,
        out=out,
    )
    return session, stt, tts, player, asked, out


class EndlessSpeech(FakeMic):
    """Fala sem parar: só o segundo toque no atalho encerra a escuta."""

    def __init__(self) -> None:
        super().__init__([])
        self.delivered = 0

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[np.ndarray]]:
        async def generate() -> AsyncIterator[np.ndarray]:
            while True:
                await asyncio.sleep(0.001)
                self.delivered += 1
                yield np.full(512, 0.9, dtype=np.float32)

        yield generate()


class Keyboard:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked: list[tuple[str, DecisionKind]] = []

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        self.asked.append((prompt, kind))
        return self.answer


def utterance(speech_frames: int = 10) -> list[np.ndarray]:
    return frames(3) + frames(speech_frames, 0.9) + frames(25)
