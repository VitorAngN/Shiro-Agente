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

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import httpx

from shiro.downloads import (
    COMPLETE_MARK,
    HUGGING_FACE,
    KNOWN_SHA256,
    DownloadError,
    Progress,
    download,
    ensure_hf_files,
)

# Reexportados para quem já importava daqui (testes e CLI).
__all__ = [
    "HUGGING_FACE",
    "KNOWN_SHA256",
    "DownloadError",
    "Progress",
    "download",
    "ensure_hf_files",
]

WHISPER_FILES = {
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
    "preprocessor_config.json",
}

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_MODELS = {
    "int8": "kokoro-v1.0.int8.onnx",
    "fp16": "kokoro-v1.0.fp16.onnx",
    "fp32": "kokoro-v1.0.onnx",
}
KOKORO_VOICES = "voices-v1.0.bin"
OPENWAKEWORD_RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
OPENWAKEWORD_BASE = ("melspectrogram.onnx", "embedding_model.onnx")
OPENWAKEWORD_BUILTIN = {
    "hey_jarvis": "hey_jarvis_v0.1.onnx",
    "alexa": "alexa_v0.1.onnx",
    "hey_mycroft": "hey_mycroft_v0.1.onnx",
}


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
    return (whisper_dir(data_dir, model) / COMPLETE_MARK).is_file()


async def ensure_whisper(
    client: httpx.AsyncClient, data_dir: Path, model: str, progress: Progress | None = None
) -> Path:
    """Pasta com o modelo do Whisper pronto, baixando o que faltar."""
    repo = whisper_repo(model)
    try:
        return await ensure_hf_files(
            client,
            whisper_dir(data_dir, model),
            repo,
            WHISPER_FILES,
            progress,
            required="model.bin",
        )
    except DownloadError as exc:
        if "não tem" in str(exc):
            msg = f"{repo} não parece um modelo do faster-whisper"
            raise DownloadError(msg) from exc
        raise


@dataclass(frozen=True)
class WakeWordFiles:
    melspectrogram: Path
    embedding: Path
    wakeword: Path


async def ensure_openwakeword(
    client: httpx.AsyncClient, data_dir: Path, model: str, progress: Progress | None = None
) -> WakeWordFiles:
    """Modelos de base do openWakeWord e o da palavra (embutido pelo nome, ou um .onnx próprio)."""
    folder = data_dir / "models" / "openwakeword"
    for name in OPENWAKEWORD_BASE:
        if not (folder / name).is_file():
            await download(client, OPENWAKEWORD_RELEASE + name, folder / name, progress)
    if model in OPENWAKEWORD_BUILTIN:
        wakeword = folder / OPENWAKEWORD_BUILTIN[model]
        if not wakeword.is_file():
            await download(client, OPENWAKEWORD_RELEASE + wakeword.name, wakeword, progress)
    else:
        wakeword = Path(model).expanduser()  # noqa: ASYNC240 - só monta o caminho
        if not wakeword.is_file():
            msg = f'modelo de palavra de ativação "{model}" não encontrado'
            raise DownloadError(msg)
    return WakeWordFiles(folder / OPENWAKEWORD_BASE[0], folder / OPENWAKEWORD_BASE[1], wakeword)
