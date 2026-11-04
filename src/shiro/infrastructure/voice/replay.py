"""Microfone de reprodução: entrega um áudio gravado como se fosse o microfone.

Serve para medir a escuta (VAD, palavra de ativação, Whisper) sem falar nem tocar
nada: ``shiro voice bench --wake`` e os testes.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import numpy as np

from shiro.domain.voice.audio import STT_RATE, Audio, Samples, concat, silence
from shiro.domain.voice.endpointing import FRAME


class ReplayMicrophone:
    def __init__(self, clips: list[Audio], gap_ms: int = 800) -> None:
        parts: list[Audio] = []
        for clip in clips:
            parts += [silence(gap_ms, STT_RATE), clip.resampled(STT_RATE)]
        parts.append(silence(gap_ms * 2, STT_RATE))
        self.audio = concat(parts, STT_RATE)

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
        async def generate() -> AsyncIterator[Samples]:
            samples = self.audio.samples
            for start in range(0, len(samples) - FRAME + 1, FRAME):
                await asyncio.sleep(0)
                yield samples[start : start + FRAME].astype(np.float32)

        yield generate()
