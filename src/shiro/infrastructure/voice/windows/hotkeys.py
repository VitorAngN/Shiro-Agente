"""Atalhos globais com ``RegisterHotKey``: funcionam com qualquer janela em foco.

Uma thread própria registra os atalhos e roda o laço de mensagens do Windows;
cada ``WM_HOTKEY`` vira uma ação na fila do asyncio.
"""

from __future__ import annotations

import asyncio
import ctypes
import threading
from collections.abc import Mapping
from ctypes import wintypes

from shiro.domain.voice.hotkeys import MOD_NOREPEAT, HotkeyError, parse_hotkey

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012


class WindowsHotkeys:
    def __init__(self, bindings: Mapping[str, str]) -> None:
        """``bindings``: ação → atalho, ex.: ``{"talk": "ctrl+alt+space"}``."""
        self._hotkeys = {action: parse_hotkey(text) for action, text in bindings.items()}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: str | None = None

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run, args=(loop,), daemon=True, name="hotkeys")
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise HotkeyError(self._error)

    async def next(self) -> str:
        return await self._queue.get()

    def stop(self) -> None:
        if self._thread is not None and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)  # type: ignore[attr-defined]
            self._thread.join(2)

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._thread_id = kernel32.GetCurrentThreadId()
        actions: dict[int, str] = {}
        for number, (action, hotkey) in enumerate(self._hotkeys.items(), start=1):
            if not user32.RegisterHotKey(None, number, hotkey.modifiers | MOD_NOREPEAT, hotkey.key):
                self._error = (
                    f'o atalho "{hotkey.text}" já está em uso por outro programa; '
                    "troque em voice.push_to_talk_hotkey ou voice.stop_hotkey"
                )
                for registered in actions:
                    user32.UnregisterHotKey(None, registered)
                self._ready.set()
                return
            actions[number] = action
        self._ready.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == _WM_HOTKEY and message.wParam in actions:
                    loop.call_soon_threadsafe(self._queue.put_nowait, actions[message.wParam])
        finally:
            for number in actions:
                user32.UnregisterHotKey(None, number)
