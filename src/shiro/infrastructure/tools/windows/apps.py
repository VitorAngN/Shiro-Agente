"""Abrir e fechar apps no Windows.

``launch`` aceita um caminho, um comando do PATH (``code``) ou um URI
(``spotify:``) e usa o ``ShellExecute`` do Windows, sem shell intermediário.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

import psutil


class WindowsAppLauncher:
    async def launch(self, target: str) -> None:
        await asyncio.to_thread(_launch, target)

    async def close(self, process: str) -> int:
        return await asyncio.to_thread(_close, process)


def _launch(target: str) -> None:
    if sys.platform != "win32":
        msg = "abrir apps disponível só no Windows"
        raise RuntimeError(msg)
    expanded = os.path.expandvars(target)
    os.startfile(shutil.which(expanded) or expanded)  # noqa: S606 - alvo vem da lista permitida


def _close(process: str) -> int:
    wanted = process.casefold()
    victims = [
        proc
        for proc in psutil.process_iter(["name"])
        if str(proc.info.get("name") or "").casefold() == wanted
    ]
    for proc in victims:
        try:
            proc.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(victims, timeout=3)
    return len(victims) - len(alive)
