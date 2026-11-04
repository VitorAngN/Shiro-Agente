"""Início e fim da frase a partir da probabilidade de fala de cada quadro.

Lógica pura, sem áudio real: testável com probabilidades sintéticas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from shiro.domain.voice.audio import STT_RATE, Audio, Samples
from shiro.structures.ring import RingBuffer

FRAME = 512


"""Amostras por quadro: 32 ms a 16 kHz, o tamanho que o Silero espera."""


FRAME_MS = FRAME * 1000 // STT_RATE


class Status(Enum):
    WAITING = "waiting"
    SPEAKING = "speaking"
    DONE = "done"
    NO_SPEECH = "no_speech"


@dataclass
class EndpointConfig:
    threshold: float = 0.5
    start_timeout_s: float = 6.0
    end_silence_ms: int = 700
    max_utterance_s: float = 15.0
    pre_roll_ms: int = 300
    start_frames: int = 3
    """Quadros seguidos acima do limiar para considerar que a fala começou (~100 ms)."""


@dataclass
class Endpointer:
    """Decide início e fim da frase a partir da probabilidade de fala de cada quadro.

    A fala começa depois de ``start_frames`` quadros seguidos acima do limiar e
    termina depois de ``end_silence_ms`` abaixo de ``threshold - 0.15`` (histerese,
    para pausas curtas entre palavras não cortarem a frase).
    """

    config: EndpointConfig = field(default_factory=EndpointConfig)
    status: Status = Status.WAITING
    _frames: list[Samples] = field(default_factory=list[Samples])
    _pre_roll: RingBuffer[Samples] | None = None
    """Enquanto espera a fala: só os últimos quadros, sem copiar a lista a cada quadro."""
    _seen: int = 0
    _voiced_run: int = 0
    _silent_run: int = 0
    _speech_frames: int = 0

    def push(self, frame: Samples, probability: float) -> Status:
        if self.status in (Status.DONE, Status.NO_SPEECH):
            return self.status
        cfg = self.config
        self._seen += 1
        if self.status is Status.WAITING:
            if self._pre_roll is None:
                self._pre_roll = RingBuffer(cfg.start_frames + cfg.pre_roll_ms // FRAME_MS)
            self._pre_roll.append(frame)
            self._voiced_run = self._voiced_run + 1 if probability >= cfg.threshold else 0
            if self._voiced_run >= cfg.start_frames:
                self._frames = self._pre_roll.to_list()
                self._pre_roll.clear()
                self._speech_frames = len(self._frames)
                self.status = Status.SPEAKING
            elif self._seen * FRAME_MS >= cfg.start_timeout_s * 1000:
                self.status = Status.NO_SPEECH
            return self.status
        self._frames.append(frame)
        self._speech_frames += 1
        silent = probability < cfg.threshold - 0.15
        self._silent_run = self._silent_run + 1 if silent else 0
        if self._silent_run * FRAME_MS >= cfg.end_silence_ms:
            self._frames = self._frames[: len(self._frames) - self._silent_run + 3]
            self.status = Status.DONE
        elif self._speech_frames * FRAME_MS >= cfg.max_utterance_s * 1000:
            self.status = Status.DONE
        return self.status

    def audio(self) -> Audio:
        if not self._frames and self._pre_roll:  # ainda esperando (ou desistiu): o pré-roll
            return Audio(np.concatenate(self._pre_roll.to_list()).astype(np.float32), STT_RATE)
        if not self._frames:
            return Audio.empty(STT_RATE)
        return Audio(np.concatenate(self._frames).astype(np.float32), STT_RATE)
