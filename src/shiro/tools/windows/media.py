"""Teclas de mídia do Windows (as mesmas do teclado), via ``keybd_event``."""

from __future__ import annotations

import asyncio
import sys

from shiro.tools.builtin.media import MediaAction

_VK_MEDIA_NEXT_TRACK = 0xB0
_VK_MEDIA_PREV_TRACK = 0xB1
_VK_MEDIA_PLAY_PAUSE = 0xB3
_KEYEVENTF_EXTENDEDKEY = 0x1
_KEYEVENTF_KEYUP = 0x2

_KEYS: dict[str, int] = {
    "play": _VK_MEDIA_PLAY_PAUSE,
    "pause": _VK_MEDIA_PLAY_PAUSE,
    "next": _VK_MEDIA_NEXT_TRACK,
    "previous": _VK_MEDIA_PREV_TRACK,
}


class WindowsMediaKeys:
    async def press(self, action: MediaAction) -> None:
        await asyncio.to_thread(_tap, _KEYS[action])


def _tap(virtual_key: int) -> None:
    if sys.platform != "win32":
        msg = "teclas de mídia disponíveis só no Windows"
        raise RuntimeError(msg)
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(virtual_key, 0, _KEYEVENTF_EXTENDEDKEY, 0)
    user32.keybd_event(virtual_key, 0, _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP, 0)
