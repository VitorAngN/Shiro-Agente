"""Embedder ONNX (média dos tokens, prefixos) e a escolha do embedder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from shiro.config.settings import MemorySettings
from shiro.domain.memory.embedding import HashingEmbedder
from shiro.infrastructure.embeddings.onnx import OnnxEmbedder
from shiro.infrastructure.embeddings.setup import build_embedder, embedding_dir
from shiro.infrastructure.system.downloads import COMPLETE_MARK


class FakeTokenizer:
    def encode_batch(self, texts: list[str]) -> list[Any]:
        width = max(len(t.split()) for t in texts)
        return [
            type(
                "E",
                (),
                {
                    "ids": [len(w) for w in t.split()] + [1] * (width - len(t.split())),
                    "attention_mask": [1] * len(t.split()) + [0] * (width - len(t.split())),
                },
            )()
            for t in texts
        ]


class FakeSession:
    def __init__(self) -> None:
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, _: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        ids = feed["input_ids"].astype(np.float32)
        return [np.stack([ids, ids * 0 + 1, ids * 2], axis=-1)]


async def test_e5_embedder_pools_and_prefixes(tmp_path: Path) -> None:
    embedder = OnnxEmbedder(
        model=tmp_path / "m.onnx",
        tokenizer=tmp_path / "t.json",
        label="e5",
        query_prefix="query: ",
        relevant_score=0.83,
    )
    session = FakeSession()

    def fake_load() -> None:
        embedder._tokenizer, embedder._session = FakeTokenizer(), session  # pyright: ignore[reportPrivateUsage]
        embedder._inputs = {"input_ids", "attention_mask", "token_type_ids"}  # pyright: ignore[reportPrivateUsage]

    embedder._load = fake_load  # type: ignore[method-assign]
    vectors = await embedder.embed(["oi", "tudo bem por aí"], query=True)

    assert vectors.shape == (2, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert "token_type_ids" in session.feeds[0]
    assert embedder.name == "onnx:e5" and embedder.relevant_score == 0.83


def test_build_embedder_falls_back_without_the_model(tmp_path: Path) -> None:
    settings = MemorySettings()
    assert isinstance(build_embedder(settings, tmp_path), HashingEmbedder)
    folder = embedding_dir(tmp_path, settings.embedding_model)
    folder.mkdir(parents=True)
    (folder / COMPLETE_MARK).write_text("ok")
    assert isinstance(build_embedder(settings, tmp_path), OnnxEmbedder)
    old_style = MemorySettings(embedding_model="nomic-embed-text")  # nome do Ollama, sem "/"
    assert isinstance(build_embedder(old_style, tmp_path), HashingEmbedder)
