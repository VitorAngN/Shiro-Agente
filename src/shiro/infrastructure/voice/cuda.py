"""Bibliotecas da NVIDIA para o Whisper na placa de vídeo (``uv sync --extra gpu``).

Os pacotes ``nvidia-cublas-cu12`` e ``nvidia-cudnn-cu12`` trazem as DLLs dentro do
ambiente Python, longe do PATH; o CTranslate2 só as acha se a pasta for anunciada.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)
_done = False


def library_dirs() -> list[Path]:
    """Pastas ``nvidia/*/bin`` (Windows) ou ``nvidia/*/lib`` (Linux) do ambiente."""
    folders: list[Path] = []
    for entry in sys.path:
        root = Path(entry) / "nvidia"
        if not root.is_dir():
            continue
        for package in sorted(root.iterdir()):
            for sub in ("bin", "lib"):
                candidate = package / sub
                if candidate.is_dir():
                    folders.append(candidate)
    return folders


def prepare() -> bool:
    """Anuncia as DLLs da NVIDIA; ``False`` se o extra ``gpu`` não estiver instalado."""
    global _done
    if _done:
        return True
    folders = library_dirs()
    if not folders:
        return False
    for folder in folders:
        if sys.platform == "win32":
            os.add_dll_directory(str(folder))
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    _done = True
    log.info("CUDA: %d pastas de bibliotecas da NVIDIA", len(folders))
    return True
