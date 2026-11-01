"""Modelo de embedding da memória: onde fica, como baixar e qual usar."""

from __future__ import annotations

from pathlib import Path

import httpx

from shiro.downloads import COMPLETE_MARK, Progress, ensure_hf_files
from shiro.memory.embedding import E5Embedder, Embedder, HashingEmbedder
from shiro.settings import MemorySettings


def embedding_dir(data_dir: Path, repo: str) -> Path:
    return data_dir / "models" / "embeddings" / repo.replace("/", "--")


def embedding_ready(settings: MemorySettings, data_dir: Path) -> bool:
    repo = settings.embedding_model
    return "/" in repo and (embedding_dir(data_dir, repo) / COMPLETE_MARK).is_file()


def build_embedder(settings: MemorySettings, data_dir: Path) -> Embedder:
    """O modelo e5 se já foi baixado; senão, a reserva por palavras (funciona sem download)."""
    if not embedding_ready(settings, data_dir):
        return HashingEmbedder()
    folder = embedding_dir(data_dir, settings.embedding_model)
    return E5Embedder(
        model=folder / settings.embedding_file,
        tokenizer=folder / "tokenizer.json",
        label=settings.embedding_model.rsplit("/", 1)[-1],
    )


async def ensure_embedding_model(
    client: httpx.AsyncClient,
    settings: MemorySettings,
    data_dir: Path,
    progress: Progress | None = None,
) -> Path:
    repo = settings.embedding_model
    files = {settings.embedding_file, "tokenizer.json", "config.json"}
    return await ensure_hf_files(
        client,
        embedding_dir(data_dir, repo),
        repo,
        files,
        progress,
        required=settings.embedding_file,
    )
