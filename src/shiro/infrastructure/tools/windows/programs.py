"""Programas do menu Iniciar (``Get-StartApps``) e janelas abertas no Windows."""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time

from shiro.infrastructure.tools.windows.control import bring_forward, usable_window

log = logging.getLogger(__name__)

_REFRESH_S = 600.0
_CREATE_NO_WINDOW = 0x08000000


def read_start_apps() -> dict[str, str]:
    """Nome → AppID de tudo o que aparece no menu Iniciar (programas e apps da Store)."""
    if sys.platform != "win32":
        return {}
    command = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    completed = subprocess.run(  # noqa: S603 - comando fixo
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=_CREATE_NO_WINDOW,
        check=False,
    )
    data = json.loads(completed.stdout or "[]")
    rows = data if isinstance(data, list) else [data]
    apps: dict[str, str] = {}
    for row in rows:
        name, app_id = str(row.get("Name") or "").strip(), str(row.get("AppID") or "").strip()
        if (
            name
            and app_id
            and "uninstall" not in name.casefold()
            and "desinstal" not in name.casefold()
        ):
            apps.setdefault(name, app_id)
    return apps


def windows_by_title() -> dict[str, int]:
    if sys.platform != "win32":
        return {}
    user32 = ctypes.windll.user32
    found: dict[str, int] = {}
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int | None, _: int | None) -> bool:
        handle = int(hwnd or 0)
        if handle and usable_window(handle, minimized=True):
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(ctypes.c_void_p(handle), buffer, 512)
            found.setdefault(buffer.value, handle)
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


class WindowsPrograms:
    def __init__(self) -> None:
        self._apps: dict[str, str] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()
        threading.Thread(target=self._refresh, name="shiro-start-apps", daemon=True).start()

    def _refresh(self) -> None:
        with self._lock:
            try:
                self._apps = read_start_apps()
                self._loaded_at = time.monotonic()
                log.info("menu Iniciar: %d programas", len(self._apps))
            except (OSError, ValueError, subprocess.SubprocessError):
                log.warning("não consegui ler o menu Iniciar", exc_info=True)

    def program_names(self) -> list[str]:
        if time.monotonic() - self._loaded_at > _REFRESH_S and not self._lock.locked():
            threading.Thread(target=self._refresh, daemon=True).start()
        return list(self._apps)

    def window_titles(self) -> list[str]:
        return list(windows_by_title())

    async def launch(self, name: str) -> None:
        app_id = self._apps.get(name)
        if app_id is None:
            msg = f"programa desconhecido: {name}"
            raise ValueError(msg)
        await asyncio.to_thread(_start, app_id)

    async def focus(self, title: str) -> None:
        await asyncio.to_thread(_focus, title)


def _start(app_id: str) -> None:
    if sys.platform != "win32":
        msg = "abrir programas disponível só no Windows"
        raise RuntimeError(msg)
    os.startfile(f"shell:AppsFolder\\{app_id}")  # noqa: S606 - AppID vem do menu Iniciar


def _focus(title: str) -> None:
    if sys.platform != "win32":
        return
    hwnd = windows_by_title().get(title)
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    if user32.IsIconic(ctypes.c_void_p(hwnd)):
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
    bring_forward(hwnd)
