"""openWakeWord em ONNX puro, sem o pacote ``openwakeword`` (ADR-0016).

O pacote publicado no PyPI parou na 0.4 e puxa scipy e scikit-learn. O
detector em si são três modelos ONNX em sequência, rodados aqui com o mesmo
onnxruntime que o Whisper e o Kokoro já usam:

1. **melspectrograma** do áudio (16 kHz, PCM 16 bits), transformado por ``x/10 + 2``;
2. **embedding** (modelo ``speech_embedding`` do Google) a cada 8 quadros de mel,
   numa janela de 76 quadros → vetor de 96 posições;
3. **classificador** da palavra de ativação sobre os últimos 16 embeddings → nota de 0 a 1.

O áudio entra em blocos de 1280 amostras (80 ms). Código e modelos de base do
openWakeWord são Apache-2.0; os modelos de palavra pré-treinados (como
``hey_jarvis``) são CC BY-NC-SA 4.0, ou seja, só para uso não comercial.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

CHUNK = 1280
"""Amostras por bloco: 80 ms a 16 kHz."""
_MEL_WINDOW = 76
_MEL_STEP = 8
_WARMUP_CHUNKS = 5  # o openWakeWord zera as primeiras notas depois de reiniciar

type Pcm16 = npt.NDArray[np.int16]


def _session(path: Path) -> Any:
    import onnxruntime  # pyright: ignore[reportMissingTypeStubs]

    options: Any = onnxruntime.SessionOptions()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    options.log_severity_level = 4
    return onnxruntime.InferenceSession(  # pyright: ignore[reportUnknownMemberType]
        str(path), providers=["CPUExecutionProvider"], sess_options=options
    )


class OpenWakeWord:
    def __init__(self, *, melspectrogram: Path, embedding: Path, wakeword: Path) -> None:
        self._mel_model = _session(melspectrogram)
        self._embedding_model = _session(embedding)
        self._wake_model = _session(wakeword)
        inputs = self._wake_model.get_inputs()
        self._wake_input: str = inputs[0].name
        self._frames: int = int(inputs[0].shape[1])  # quantos embeddings o classificador olha (16)
        self.reset()

    def reset(self) -> None:
        self._raw = np.zeros(0, dtype=np.int16)
        self._mel = np.ones((_MEL_WINDOW, 32), dtype=np.float32)
        noise = np.random.default_rng(0).integers(-1000, 1000, 16_000 * 4).astype(np.int16)
        self._features = self._embeddings_of(noise)
        self._seen = 0

    def score(self, chunk: Pcm16) -> float:
        """Nota de 0 a 1 para o bloco de 1280 amostras mais recente."""
        if chunk.shape != (CHUNK,):
            msg = f"o detector espera blocos de {CHUNK} amostras"
            raise ValueError(msg)
        self._raw = np.concatenate([self._raw, chunk])[-(CHUNK + 160 * 3) :]
        self._mel = np.vstack([self._mel, self._melspectrogram(self._raw)])[-10 * 97 :]
        window = self._mel[-_MEL_WINDOW:].astype(np.float32)[None, :, :, None]
        embedding = self._embedding_model.run(None, {"input_1": window})[0].squeeze()
        self._features = np.vstack([self._features, embedding])[-120:]
        self._seen += 1
        features = self._features[-self._frames :][None, :, :].astype(np.float32)
        output = self._wake_model.run(None, {self._wake_input: features})[0]
        if self._seen <= _WARMUP_CHUNKS:
            return 0.0
        return float(np.ravel(output)[0])

    def _melspectrogram(self, audio: Pcm16) -> npt.NDArray[np.float32]:
        output = self._mel_model.run(None, {"input": audio[None, :].astype(np.float32)})[0]
        return (np.squeeze(output) / 10 + 2).astype(np.float32)

    def _embeddings_of(self, audio: Pcm16) -> npt.NDArray[np.float32]:
        mel = self._melspectrogram(audio)
        windows = [
            mel[i : i + _MEL_WINDOW]
            for i in range(0, mel.shape[0], _MEL_STEP)
            if mel[i : i + _MEL_WINDOW].shape[0] == _MEL_WINDOW
        ]
        batch = np.expand_dims(np.array(windows), axis=-1).astype(np.float32)
        return self._embedding_model.run(None, {"input_1": batch})[0].squeeze().astype(np.float32)
