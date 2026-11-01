"""Fala para texto com faster-whisper, na CPU em int8 (ADR-0004, ADR-0010).

O modelo é carregado uma vez e reaproveitado. A transcrição roda numa thread
para não travar o laço de eventos. Na primeira vez, o faster-whisper baixa o
modelo do Hugging Face para o cache do usuário.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from shiro.settings import STTSettings
from shiro.voice.audio import STT_RATE, Audio
from shiro.voice.ports import Transcript
from shiro.voice.speech import clean_transcript

# Segmentos com muita chance de não ser fala e baixa confiança são descartados.
_NO_SPEECH = 0.6
_LOW_CONFIDENCE = -1.0


class _Segment(Protocol):
    text: str
    no_speech_prob: float
    avg_logprob: float


type ModelFactory = Callable[[STTSettings], Any]


def _whisper(settings: STTSettings) -> Any:
    from faster_whisper import WhisperModel  # pyright: ignore[reportMissingTypeStubs]

    return WhisperModel(
        settings.model,
        device=settings.device,
        compute_type=settings.compute_type,
        cpu_threads=settings.threads,
    )


def vocabulary_prompt(name: str, apps: Sequence[str]) -> str:
    """Prompt inicial com nomes que o Whisper erraria sem contexto ("Shiro", apps)."""
    listed = ", ".join(apps[:12])
    base = f"{name}, abre o {apps[0]}." if apps else f"{name}."
    extra = f" Aplicativos: {listed}." if listed else ""
    return f"{base} Volume, atividade, lembrete, prova, trabalho.{extra}"


class FasterWhisperSTT:
    def __init__(
        self,
        settings: STTSettings,
        *,
        prompt: str = "",
        factory: ModelFactory = _whisper,
    ) -> None:
        self._settings = settings
        self._prompt = prompt or None
        self._factory = factory
        self._model: Any = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return f"faster-whisper/{self._settings.model}"

    async def load(self) -> None:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._factory, self._settings)

    async def transcribe(self, audio: Audio) -> Transcript:
        await self.load()
        clip = audio.resampled(STT_RATE)
        started = time.perf_counter()
        text = await asyncio.to_thread(self._run, clip)
        latency = round((time.perf_counter() - started) * 1000)
        return Transcript(text=text, audio_s=clip.duration, latency_ms=latency)

    def _run(self, clip: Audio) -> str:
        segments, _info = self._model.transcribe(
            clip.samples,
            language=self._settings.language,
            beam_size=self._settings.beam_size,
            vad_filter=False,  # o VAD já recortou a frase
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=self._prompt,
        )
        kept: list[str] = []
        for segment in segments:
            seg: _Segment = segment
            if seg.no_speech_prob > _NO_SPEECH and seg.avg_logprob < _LOW_CONFIDENCE:
                continue
            kept.append(seg.text.strip())
        return clean_transcript(" ".join(kept))
