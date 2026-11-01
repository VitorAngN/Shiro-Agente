"""Arquivos de modelo da voz: onde ficam e como baixar com verificação.

O Kokoro vem das releases do projeto kokoro-onnx (MIT; pesos Kokoro-82M sob
Apache-2.0). Os arquivos baixados ficam em ``<dados>/models/kokoro``. Para os
arquivos com hash conhecido, um download diferente é rejeitado.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

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
    """O pacote opcional ``kokoro-onnx`` está instalado (``uv sync --extra kokoro``)?"""
    return importlib.util.find_spec("kokoro_onnx") is not None


async def download(
    client: httpx.AsyncClient, url: str, dest: Path, progress: Progress | None = None
) -> str:
    """Baixa para ``dest`` (via arquivo ``.part``) e devolve o SHA-256."""
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
    expected = KNOWN_SHA256.get(dest.name)
    if expected is not None and sha != expected:
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
