"""Modelo de embedding da memória: onde fica, como baixar e qual usar."""

from __future__ import annotations

from pathlib import Path

import httpx

from shiro.downloads import COMPLETE_MARK, Progress, ensure_hf_files
from shiro.memory.embedding import Embedder, HashingEmbedder, OnnxEmbedder
from shiro.settings import MemorySettings

# Prefixos e limiares calibrados no PC de referência (ADR-0017): 10 perguntas que
# combinam com um fato guardado e 8 que não combinam com nenhum.
KNOWN_MODELS: dict[str, tuple[str, str, float, float]] = {
    # repositório: (prefixo da pergunta, prefixo do fato, entra no contexto, pode esquecer)
    "Xenova/paraphrase-multilingual-MiniLM-L12-v2": ("", "", 0.43, 0.55),
    "Xenova/paraphrase-multilingual-mpnet-base-v2": ("", "", 0.45, 0.55),
    "Xenova/multilingual-e5-small": ("query: ", "passage: ", 0.86, 0.9),
    "Xenova/multilingual-e5-base": ("query: ", "passage: ", 0.82, 0.88),
}


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
    query, passage, relevant, match = KNOWN_MODELS.get(settings.embedding_model, ("", "", 0.5, 0.6))
    return OnnxEmbedder(
        model=folder / settings.embedding_file,
        tokenizer=folder / "tokenizer.json",
        label=settings.embedding_model.rsplit("/", 1)[-1],
        query_prefix=query,
        passage_prefix=passage,
        relevant_score=settings.min_score or relevant,
        match_score=match,
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
