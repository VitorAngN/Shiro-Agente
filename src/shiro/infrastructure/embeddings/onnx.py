"""Modelo de sentenças multilíngue em ONNX int8 (~113 MB), na CPU.

Usa o ``tokenizers`` que o faster-whisper já instala. Entende que "qual é o meu
time?" combina com "eu torço pro Coritiba".
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from shiro.domain.memory.embedding import Vectors


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
