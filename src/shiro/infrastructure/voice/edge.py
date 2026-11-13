"""Voz neural da Microsoft (as do Edge: Francisca, Thalita) pelo pacote ``edge-tts``.

Precisa de internet e usa um serviço não oficial: pode mudar ou sair do ar. Por
isso ``FallbackTTS`` cai para a voz local (Kokoro ou Windows) quando a nuvem falha.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from shiro.domain.voice.audio import Audio
from shiro.domain.voice.ports import TextToSpeech

log = logging.getLogger(__name__)

_RATE = 24_000
_RETRY_AFTER_S = 120.0  # depois de uma falha, tenta a nuvem de novo só depois disso


def _percent(value: float) -> str:
    return f"{round((value - 1) * 100):+d}%"


class EdgeTTS:
    def __init__(
        self, *, voice: str, speed: float = 1.0, pitch_hz: int = 0, timeout_s: float = 15.0
    ) -> None:
        self._voice = voice
        self._rate = _percent(speed)
        self._pitch = f"{pitch_hz:+d}Hz"
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return f"Microsoft {self._voice}"

    async def synthesize(self, text: str) -> Audio:
        import edge_tts

        communicate = edge_tts.Communicate(
            text, self._voice, rate=self._rate, pitch=self._pitch, connect_timeout=5
        )
        chunks: list[bytes] = []

        async def collect() -> None:
            async for message in communicate.stream():
                data = message.get("data")
                if message["type"] == "audio" and data:
                    chunks.append(data)

        await asyncio.wait_for(collect(), self._timeout_s)
        if not chunks:
            msg = "a voz da Microsoft não devolveu áudio"
            raise RuntimeError(msg)
        return await asyncio.to_thread(decode_mp3, b"".join(chunks))

    async def aclose(self) -> None:
        return None


def decode_mp3(data: bytes) -> Audio:
    import miniaudio

    decoded = miniaudio.decode(
        data, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1, sample_rate=_RATE
    )
    samples = np.frombuffer(decoded.samples, dtype=np.float32).copy()
    return Audio(samples, _RATE)


class FallbackTTS:
    """Tenta a voz principal; se falhar (sem internet), usa a reserva e tenta de novo depois."""

    def __init__(self, primary: TextToSpeech, backup: TextToSpeech) -> None:
        self._primary = primary
        self._backup = backup
        self._down_until = 0.0

    @property
    def name(self) -> str:
        return f"{self._primary.name} (reserva: {self._backup.name})"

    async def synthesize(self, text: str) -> Audio:
        if time.monotonic() >= self._down_until:
            try:
                return await self._primary.synthesize(text)
            except Exception as exc:
                log.warning("voz principal falhou (%s); usando a reserva", exc)
                self._down_until = time.monotonic() + _RETRY_AFTER_S
        return await self._backup.synthesize(text)

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._backup.aclose()
