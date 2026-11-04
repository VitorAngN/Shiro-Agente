"""Portas da voz (ADR-0004): cada etapa do pipeline troca de motor sem mexer na sessão."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from shiro.domain.voice.audio import Audio, Samples


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_s: float
    latency_ms: int
    heard: str = ""
    """O que a transcrição livre deu, quando ``text`` foi corrigido para um comando conhecido."""


class SpeechToText(Protocol):
    async def load(self) -> None:
        """Carrega o modelo antes da primeira fala (pode baixar na primeira vez)."""
        ...

    async def transcribe(self, audio: Audio) -> Transcript: ...


class PhraseScorer(Protocol):
    async def score(self, audio: Audio, phrases: Sequence[str]) -> list[float]:
        """Quanto cada frase explica o áudio: média do log da probabilidade por token."""
        ...


class TextToSpeech(Protocol):
    @property
    def name(self) -> str: ...

    async def synthesize(self, text: str) -> Audio: ...

    async def aclose(self) -> None: ...


class Player(Protocol):
    async def play(self, audio: Audio) -> bool:
        """Toca até o fim. ``False`` se foi interrompido por ``stop``."""
        ...

    def stop(self) -> None: ...


class Microphone(Protocol):
    def open(self) -> AbstractAsyncContextManager[AsyncIterator[Samples]]:
        """Quadros de 512 amostras a 16 kHz (32 ms), enquanto o contexto estiver aberto."""
        ...


class SpeechDetector(Protocol):
    def reset(self) -> None: ...

    def probability(self, frame: Samples) -> float:
        """Probabilidade de haver fala num quadro de 512 amostras a 16 kHz."""
        ...
