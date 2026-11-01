"""Arquivos de modelo da voz: onde ficam e como baixar com verificação.

* **Whisper** (CTranslate2, repositórios ``Systran/faster-whisper-*`` no Hugging
  Face): baixado pelo próprio SHIRO para ``<dados>/models/whisper``. O cliente
  do Hugging Face travava no Windows de referência (ADR-0015). Cada arquivo é
  conferido com o hash que a API do Hugging Face publica: SHA-256 nos arquivos
  grandes (LFS), SHA-1 de blob do git nos pequenos.
* **Kokoro**: releases do projeto kokoro-onnx (MIT; pesos Kokoro-82M sob
  Apache-2.0), em ``<dados>/models/kokoro``, com SHA-256 fixado no código.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

HUGGING_FACE = "https://huggingface.co"
WHISPER_FILES = {
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
    "preprocessor_config.json",
}
_COMPLETE = ".completo"

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_MODELS = {
    "int8": "kokoro-v1.0.int8.onnx",
    "fp16": "kokoro-v1.0.fp16.onnx",
    "fp32": "kokoro-v1.0.onnx",
}
KOKORO_VOICES = "voices-v1.0.bin"
# Conferidos em 2026-11-01. Variantes sem hash aqui são aceitas como vierem.
KNOWN_SHA256 = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}

type Progress = Callable[[str, int, int | None], None]


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class KokoroFiles:
    model: Path
    voices: Path

    @property
    def present(self) -> bool:
        return self.model.is_file() and self.voices.is_file()


def kokoro_files(data_dir: Path, variant: str) -> KokoroFiles:
    folder = data_dir / "models" / "kokoro"
    return KokoroFiles(model=folder / KOKORO_MODELS[variant], voices=folder / KOKORO_VOICES)


def kokoro_installed() -> bool:
    """O pacote ``kokoro-onnx`` está instalado (grupo ``kokoro`` do uv, padrão no ``uv sync``)?"""
    return importlib.util.find_spec("kokoro_onnx") is not None


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


async def ensure_kokoro(
    client: httpx.AsyncClient, data_dir: Path, variant: str, progress: Progress | None = None
) -> KokoroFiles:
    files = kokoro_files(data_dir, variant)
    for path in (files.voices, files.model):
        if not path.is_file():
            await download(client, KOKORO_RELEASE + path.name, path, progress)
    return files


def whisper_repo(model: str) -> str:
    """ "small" → "Systran/faster-whisper-small"; um id com "/" vale como está."""
    return model if "/" in model else f"Systran/faster-whisper-{model}"


def whisper_dir(data_dir: Path, model: str) -> Path:
    return data_dir / "models" / "whisper" / whisper_repo(model).replace("/", "--")


def whisper_ready(data_dir: Path, model: str) -> bool:
    return (whisper_dir(data_dir, model) / _COMPLETE).is_file()


async def ensure_whisper(
    client: httpx.AsyncClient, data_dir: Path, model: str, progress: Progress | None = None
) -> Path:
    """Pasta com o modelo do Whisper pronto, baixando o que faltar."""
    folder = whisper_dir(data_dir, model)
    if (folder / _COMPLETE).is_file():
        return folder
    repo = whisper_repo(model)
    response = await client.get(f"{HUGGING_FACE}/api/models/{repo}/tree/main")
    if response.status_code != 200:
        msg = f"modelo {repo} não encontrado no Hugging Face (HTTP {response.status_code})"
        raise DownloadError(msg)
    entries: list[dict[str, Any]] = response.json()
    wanted = [e for e in entries if e.get("type") == "file" and e.get("path") in WHISPER_FILES]
    if not any(e["path"] == "model.bin" for e in wanted):
        msg = f"{repo} não parece um modelo do faster-whisper"
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
    (folder / _COMPLETE).write_text(repo, encoding="utf-8")
    return folder
