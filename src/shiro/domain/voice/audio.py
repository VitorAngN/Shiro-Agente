"""Áudio em memória: amostras mono float32 de -1 a 1, WAV e bipes.

Tudo na voz da SHIRO passa por aqui: o microfone entrega quadros de 16 kHz, o
Whisper espera 16 kHz, o Kokoro gera 24 kHz e o SAPI 22.050 Hz.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

STT_RATE = 16_000
"""Taxa do microfone, do VAD e do Whisper."""

type Samples = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Audio:
    samples: Samples
    rate: int

    @classmethod
    def empty(cls, rate: int = STT_RATE) -> Audio:
        return cls(np.zeros(0, dtype=np.float32), rate)

    @property
    def duration(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0

    def resampled(self, rate: int) -> Audio:
        """Reamostragem linear: suficiente para voz e sem dependências."""
        if rate == self.rate or len(self.samples) == 0:
            return Audio(self.samples, rate)
        count = round(len(self.samples) * rate / self.rate)
        positions = np.linspace(0, len(self.samples) - 1, count)
        resampled = np.interp(positions, np.arange(len(self.samples)), self.samples)
        return Audio(resampled.astype(np.float32), rate)

    def scaled(self, volume: float) -> Audio:
        return Audio((self.samples * np.float32(volume)).astype(np.float32), self.rate)

    def to_wav(self) -> bytes:
        pcm = (np.clip(self.samples, -1.0, 1.0) * 32767).astype("<i2")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(self.rate)
            out.writeframes(pcm.tobytes())
        return buffer.getvalue()

    @classmethod
    def from_wav(cls, data: bytes) -> Audio:
        with wave.open(io.BytesIO(data), "rb") as source:
            if source.getsampwidth() != 2:
                msg = "só WAV de 16 bits é suportado"
                raise ValueError(msg)
            channels = source.getnchannels()
            rate = source.getframerate()
            raw = source.readframes(source.getnframes())
        return cls.from_pcm16(raw, rate, channels=channels)

    @classmethod
    def from_pcm16(cls, raw: bytes, rate: int, *, channels: int = 1) -> Audio:
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        return cls(pcm.astype(np.float32), rate)


def concat(parts: list[Audio], rate: int) -> Audio:
    if not parts:
        return Audio.empty(rate)
    samples = [p.resampled(rate).samples for p in parts]
    return Audio(np.concatenate(samples).astype(np.float32), rate)


def silence(ms: int, rate: int) -> Audio:
    return Audio(np.zeros(rate * ms // 1000, dtype=np.float32), rate)


def tone(frequency: float, ms: int, *, rate: int = 24_000, volume: float = 0.2) -> Audio:
    """Bipe senoidal com rampa de 8 ms nas pontas, para não estalar."""
    count = rate * ms // 1000
    t = np.arange(count, dtype=np.float32) / rate
    wave_ = np.sin(2 * np.pi * frequency * t).astype(np.float32)
    ramp = min(count // 2, rate * 8 // 1000)
    if ramp:
        envelope = np.ones(count, dtype=np.float32)
        envelope[:ramp] = np.linspace(0, 1, ramp, dtype=np.float32)
        envelope[-ramp:] = np.linspace(1, 0, ramp, dtype=np.float32)
        wave_ *= envelope
    return Audio((wave_ * np.float32(volume)).astype(np.float32), rate)


@dataclass(frozen=True)
class Cues:
    """Sinais sonoros curtos: começou a ouvir, parou, não entendeu."""

    listening: Audio
    done: Audio
    error: Audio

    @classmethod
    def generate(cls, volume: float, rate: int = 24_000) -> Cues:
        if volume <= 0:
            nothing = Audio.empty(rate)
            return cls(nothing, nothing, nothing)
        gap = silence(30, rate)
        return cls(
            listening=concat(
                [
                    tone(660, 70, rate=rate, volume=volume),
                    gap,
                    tone(880, 90, rate=rate, volume=volume),
                ],
                rate,
            ),
            done=tone(740, 80, rate=rate, volume=volume * 0.8),
            error=concat(
                [
                    tone(330, 110, rate=rate, volume=volume),
                    gap,
                    tone(262, 140, rate=rate, volume=volume),
                ],
                rate,
            ),
        )
