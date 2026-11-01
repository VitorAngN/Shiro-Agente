"""Vetores de texto para achar memórias por semelhança (RF-42).

* ``OnnxEmbedder``: modelo de sentenças multilíngue em ONNX int8 (~113 MB), na
  CPU, com o ``tokenizers`` que o faster-whisper já instala. Entende que "qual
  é o meu time?" combina com "eu torço pro Coritiba".
* ``HashingEmbedder``: reserva sem download, por palavras e radicais. Acha
  "café" em "gosto de café", mas não sinônimos.

Os vetores saem normalizados: semelhança é o produto escalar.
"""

from __future__ import annotations

import asyncio
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from shiro.core.text import normalize

type Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Identifica o modelo; vetores de outro modelo são recalculados."""
        ...

    @property
    def relevant_score(self) -> float:
        """Semelhança mínima para uma memória entrar no contexto."""
        ...

    @property
    def match_score(self) -> float:
        """Semelhança mínima para "esquece X" apagar uma memória."""
        ...

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors: ...


_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "e", "que", "eu",
    "meu", "minha", "meus", "minhas", "pra", "para", "pro", "no", "na", "em", "com", "por",
    "se", "me", "mim", "voce", "qual", "quais", "sou", "tenho", "isso",
}  # fmt: skip


def _stems(text: str) -> list[str]:
    words = [w for w in normalize(text).replace(",", " ").replace(".", " ").split() if w]
    return [w[:5] for w in words if w not in _STOPWORDS and len(w) > 1]


class HashingEmbedder:
    """Saco de radicais com hash: sem modelo, sem download, determinístico."""

    def __init__(self, dimensions: int = 512) -> None:
        self._dimensions = dimensions

    @property
    def name(self) -> str:
        return f"hash-v1-{self._dimensions}"

    @property
    def relevant_score(self) -> float:
        return 0.3  # uma palavra em comum numa frase curta (~0,33) já conta

    @property
    def match_score(self) -> float:
        return 0.5

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors:
        vectors = np.zeros((len(texts), self._dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for stem in _stems(text):
                vectors[row, zlib.crc32(stem.encode()) % self._dimensions] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)


class OnnxEmbedder:
    """Modelo de sentenças em ONNX (tipo sentence-transformers), com média dos tokens.

    Modelos da família e5 pedem prefixos ("query: " na pergunta, "passage: " nos
    fatos); os de paráfrase não usam prefixo.
    """

    def __init__(
        self,
        *,
        model: Path,
        tokenizer: Path,
        label: str,
        query_prefix: str = "",
        passage_prefix: str = "",
        relevant_score: float = 0.5,
        match_score: float = 0.6,
        max_tokens: int = 128,
    ) -> None:
        self._model_path = model
        self._tokenizer_path = tokenizer
        self._label = label
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._relevant = relevant_score
        self._match = match_score
        self._max_tokens = max_tokens
        self._session: Any = None
        self._tokenizer: Any = None
        self._inputs: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return f"onnx:{self._label}"

    @property
    def relevant_score(self) -> float:
        return self._relevant

    @property
    def match_score(self) -> float:
        return self._match

    async def embed(self, texts: Sequence[str], *, query: bool) -> Vectors:
        async with self._lock:
            if self._session is None:
                await asyncio.to_thread(self._load)
        prefix = self._query_prefix if query else self._passage_prefix
        return await asyncio.to_thread(self._run, [prefix + t for t in texts])

    def _load(self) -> None:
        import onnxruntime  # pyright: ignore[reportMissingTypeStubs]
        from tokenizers import Tokenizer  # pyright: ignore[reportMissingTypeStubs]

        tokenizer: Any = Tokenizer.from_file(str(self._tokenizer_path))  # pyright: ignore[reportUnknownMemberType]
        tokenizer.enable_truncation(max_length=self._max_tokens)
        pad_id = tokenizer.token_to_id("<pad>")
        pad_id = 0 if pad_id is None else pad_id
        tokenizer.enable_padding(pad_id=pad_id, pad_token="<pad>")  # noqa: S106 - não é senha
        options: Any = onnxruntime.SessionOptions()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        options.intra_op_num_threads = 2
        options.log_severity_level = 4
        session: Any = onnxruntime.InferenceSession(  # pyright: ignore[reportUnknownMemberType]
            str(self._model_path), providers=["CPUExecutionProvider"], sess_options=options
        )
        self._inputs = {i.name for i in session.get_inputs()}
        self._tokenizer, self._session = tokenizer, session

    def _run(self, texts: list[str]) -> Vectors:
        encodings = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.where(norms == 0, 1, norms)).astype(np.float32)
