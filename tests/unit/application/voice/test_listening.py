"""Ouvir uma frase: microfone, detector e endpointer juntos, com terminar e cancelar."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from shiro.application.voice.listening import ListenControl, record_utterance
from shiro.domain.voice.audio import Samples
from shiro.domain.voice.endpointing import EndpointConfig
from tests.fakes.voice import FakeMic, ScriptedDetector, frames


async def test_record_utterance_finish_and_cancel() -> None:
    speech = frames(5) + frames(10, 0.9) + frames(30)
    detector = ScriptedDetector()
    audio = await record_utterance(FakeMic(speech), detector, EndpointConfig(end_silence_ms=320))
    assert audio is not None and audio.duration > 0.3
    assert detector.resets == 1

    assert await record_utterance(FakeMic(frames(10)), detector, EndpointConfig()) is None

    control = ListenControl()
    early = ListenControl()
    early.finish.set()  # tocar de novo antes de falar: nada a transcrever
    assert await record_utterance(FakeMic(frames(5)), detector, EndpointConfig(), early) is None

    class FinishMidway(FakeMic):
        @contextlib.asynccontextmanager
        async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
            async def generate() -> AsyncIterator[Samples]:
                for index, block in enumerate(self.blocks):
                    if index == 10:
                        control.finish.set()  # segundo toque com a fala em andamento
                    await asyncio.sleep(0)
                    yield block

            yield generate()

    finished = await record_utterance(
        FinishMidway(frames(200, 0.9)), detector, EndpointConfig(), control
    )
    assert finished is not None
    assert finished.duration < 0.5  # parou no toque, não no limite de 15 s

    cancelled = ListenControl()
    cancelled.cancel.set()
    assert (
        await record_utterance(FakeMic(frames(5, 0.9)), detector, EndpointConfig(), cancelled)
        is None
    )
