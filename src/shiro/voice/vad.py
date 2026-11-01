"""Detecção de fala: quando a frase começa e quando termina.

* ``SileroVAD``: o modelo Silero que já vem com o faster-whisper, rodado quadro a
  quadro (32 ms) com o estado recorrente preservado entre quadros;
* ``Endpointer``: a lógica de início e fim da frase, sem áudio real, testável
  com probabilidades sintéticas;
* ``record_utterance``: junta microfone, detector e endpointer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from shiro.voice.audio import STT_RATE, Audio, Samples
from shiro.voice.ports import Microphone, SpeechDetector

FRAME = 512
"""Amostras por quadro: 32 ms a 16 kHz, o tamanho que o Silero espera."""
FRAME_MS = FRAME * 1000 // STT_RATE
_CONTEXT = 64


class SileroVAD:
    """Silero VAD v6 em ONNX, do pacote faster-whisper (MIT), na CPU."""

    def __init__(self, model_path: Path | None = None) -> None:
        import onnxruntime  # pyright: ignore[reportMissingTypeStubs]

        if model_path is None:
            from faster_whisper.vad import get_assets_path  # pyright: ignore[reportMissingTypeStubs]

            model_path = Path(get_assets_path()) / "silero_vad_v6.onnx"  # pyright: ignore[reportUnknownArgumentType]
        options: Any = onnxruntime.SessionOptions()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session: Any = onnxruntime.InferenceSession(  # pyright: ignore[reportUnknownMemberType]
            str(model_path), providers=["CPUExecutionProvider"], sess_options=options
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, _CONTEXT), dtype=np.float32)

    def probability(self, frame: Samples) -> float:
        if frame.shape != (FRAME,):
            msg = f"o VAD espera quadros de {FRAME} amostras"
            raise ValueError(msg)
        batch = np.concatenate([self._context, frame[None, :]], axis=1)
        output, self._h, self._c = self._session.run(
            None, {"input": batch, "h": self._h, "c": self._c}
        )
        self._context = frame[None, -_CONTEXT:]
        return float(np.ravel(output)[0])


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
    _seen: int = 0
    _voiced_run: int = 0
    _silent_run: int = 0
    _speech_frames: int = 0

    def push(self, frame: Samples, probability: float) -> Status:
        if self.status in (Status.DONE, Status.NO_SPEECH):
            return self.status
        cfg = self.config
        self._seen += 1
        self._frames.append(frame)
        if self.status is Status.WAITING:
            self._voiced_run = self._voiced_run + 1 if probability >= cfg.threshold else 0
            if self._voiced_run >= cfg.start_frames:
                keep = cfg.start_frames + cfg.pre_roll_ms // FRAME_MS
                self._frames = self._frames[-keep:]
                self._speech_frames = len(self._frames)
                self.status = Status.SPEAKING
            else:
                self._frames = self._frames[-(cfg.start_frames + cfg.pre_roll_ms // FRAME_MS) :]
                if self._seen * FRAME_MS >= cfg.start_timeout_s * 1000:
                    self.status = Status.NO_SPEECH
            return self.status
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
        if not self._frames:
            return Audio.empty(STT_RATE)
        return Audio(np.concatenate(self._frames).astype(np.float32), STT_RATE)


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
