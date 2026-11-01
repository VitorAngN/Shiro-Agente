"""Instância única (ADR-0008): dois SHIROs ouvindo o mesmo microfone brigariam.

No Windows, um mutex nomeado da sessão do usuário (``Local\\SHIRO-Agente``); o
sistema o libera sozinho se o processo morrer. Nos outros sistemas, uma trava
de arquivo na pasta de dados.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from shiro import paths

_MUTEX_NAME = "Local\\SHIRO-Agente"
_ERROR_ALREADY_EXISTS = 183


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, handle: Any, release: Any) -> None:
        self._handle = handle
        self._release = release

    def release(self) -> None:
        if self._handle is not None:
            self._release(self._handle)
            self._handle = None


def single_instance(name: str = _MUTEX_NAME, *, lock_dir: Path | None = None) -> InstanceLock:
    """Só um SHIRO de voz ou bandeja por vez; senão, lança ``AlreadyRunningError``."""
    message = "a SHIRO já está rodando (bandeja ou outro terminal)"
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateMutexW(None, False, name)
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise AlreadyRunningError(message)
        return InstanceLock(handle, kernel32.CloseHandle)

    import fcntl

    folder = lock_dir or paths.data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(folder / f"{name.rsplit(chr(92), 1)[-1]}.lock", os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        raise AlreadyRunningError(message) from exc

    def release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    return InstanceLock(descriptor, release)
