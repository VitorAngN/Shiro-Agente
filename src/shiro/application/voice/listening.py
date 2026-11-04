"""Ouvir uma frase: junta microfone, detector de fala e endpointer pelas portas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from shiro.domain.voice.audio import Audio
from shiro.domain.voice.endpointing import EndpointConfig, Endpointer, Status
from shiro.domain.voice.ports import Microphone, SpeechDetector


@dataclass
class ListenControl:
    """Sinais externos durante a escuta.

    ``finish``: o usuário apertou o atalho de novo, a frase acabou;
    ``cancel``: o atalho de parar foi apertado, descarta tudo.
    """

    finish: asyncio.Event = field(default_factory=asyncio.Event)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


async def record_utterance(
    microphone: Microphone,
    detector: SpeechDetector,
    config: EndpointConfig,
    control: ListenControl | None = None,
) -> Audio | None:
    """Ouve até o fim da frase. ``None`` se ninguém falou dentro do prazo ou se cancelou."""
    control = control or ListenControl()
    detector.reset()
    endpointer = Endpointer(config)
    async with microphone.open() as frames:
        async for frame in frames:
            if control.cancel.is_set():
                return None
            status = endpointer.push(frame, detector.probability(frame))
            if control.finish.is_set():
                return endpointer.audio() if status is Status.SPEAKING else None
            if status is Status.DONE:
                return endpointer.audio()
            if status is Status.NO_SPEECH:
                return None
    return endpointer.audio() if endpointer.status is Status.SPEAKING else None
