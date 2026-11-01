"""Downloads de modelos com verificação de integridade.

Usado pela voz (Whisper, Kokoro, openWakeWord) e pela memória (embeddings).
Cada arquivo baixado é conferido:

* com o hash fixado em ``KNOWN_SHA256`` (releases do GitHub);
* ou com o hash que a API do Hugging Face publica: SHA-256 nos arquivos grandes
  (LFS), SHA-1 de blob do git nos pequenos.

O cliente do Hugging Face não é usado: no PC de referência ele travava (ADR-0015).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

HUGGING_FACE = "https://huggingface.co"
COMPLETE_MARK = ".completo"

type Progress = Callable[[str, int, int | None], None]

# Conferidos em 2026-11-01. Variantes sem hash aqui são aceitas como vierem.
KNOWN_SHA256 = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    "melspectrogram.onnx": "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
    "embedding_model.onnx": "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
    "hey_jarvis_v0.1.onnx": "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
    "alexa_v0.1.onnx": "6ff566a01d12670e8d9e3c59da32651db1575d17272a601b7f8a39283dfbae3e",
    "hey_mycroft_v0.1.onnx": "c2a311e8fa1338de89c31b3b46dc4dffd4af2f9a8d6ddead48893c2d301b1f18",
}


class DownloadError(RuntimeError):
    pass


async def download(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    progress: Progress | None = None,
    *,
    sha256: str | None = None,
    git_blob: str | None = None,
) -> str:
    """Baixa para ``dest`` (via arquivo ``.part``) e devolve o SHA-256.

    ``sha256`` e ``git_blob`` (SHA-1 de blob do git) são conferidos se informados;
    sem eles, vale o hash fixado em ``KNOWN_SHA256``, se houver.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    async with client.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != 200:
            msg = f"download de {dest.name} falhou: HTTP {response.status_code}"
            raise DownloadError(msg)
        total = int(response.headers.get("content-length", 0)) or None
        done = 0
        with partial.open("wb") as out:
            async for chunk in response.aiter_bytes(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(dest.name, done, total)
    sha = digest.hexdigest()
    expected = sha256 or KNOWN_SHA256.get(dest.name)
    mismatch = expected is not None and sha != expected
    if git_blob is not None and not mismatch:
        content = partial.read_bytes()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content, usedforsecurity=False)
        mismatch = blob.hexdigest() != git_blob
    if mismatch:
        partial.unlink(missing_ok=True)
        msg = f"{dest.name}: hash diferente do esperado; arquivo descartado"
        raise DownloadError(msg)
    partial.replace(dest)
    return sha


async def _hf_tree(client: httpx.AsyncClient, repo: str, folder: str = "") -> list[dict[str, Any]]:
    suffix = f"/{folder}" if folder else ""
    response = await client.get(f"{HUGGING_FACE}/api/models/{repo}/tree/main{suffix}")
    if response.status_code != 200:
        msg = f"modelo {repo} não encontrado no Hugging Face (HTTP {response.status_code})"
        raise DownloadError(msg)
    entries: list[dict[str, Any]] = response.json()
    return entries


async def ensure_hf_files(
    client: httpx.AsyncClient,
    folder: Path,
    repo: str,
    paths: set[str],
    progress: Progress | None = None,
    *,
    required: str,
) -> Path:
    """Baixa ``paths`` de um repositório do Hugging Face para ``folder``, conferindo cada hash."""
    if (folder / COMPLETE_MARK).is_file():
        return folder
    subfolders = sorted({p.rsplit("/", 1)[0] for p in paths if "/" in p})
    entries = await _hf_tree(client, repo)
    for sub in subfolders:
        entries += await _hf_tree(client, repo, sub)
    wanted = [e for e in entries if e.get("type") == "file" and e.get("path") in paths]
    if not any(e["path"] == required for e in wanted):
        msg = f"{repo} não tem {required}"
        raise DownloadError(msg)
    for entry in wanted:
        dest = folder / entry["path"]
        if dest.is_file() and dest.stat().st_size == entry.get("size"):
            continue
        lfs = entry.get("lfs")
        await download(
            client,
            f"{HUGGING_FACE}/{repo}/resolve/main/{entry['path']}",
            dest,
            progress,
            sha256=lfs["oid"] if lfs else None,
            git_blob=None if lfs else entry.get("oid"),
        )
    (folder / COMPLETE_MARK).write_text(repo, encoding="utf-8")
    return folder
