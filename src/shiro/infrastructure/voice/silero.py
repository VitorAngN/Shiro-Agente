"""Silero VAD v6 em ONNX (o que vem com o faster-whisper), quadro a quadro na CPU."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from shiro.domain.voice.audio import Samples
from shiro.domain.voice.endpointing import FRAME

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
