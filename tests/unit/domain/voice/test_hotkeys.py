"""Atalhos de teclado escritos no shiro.toml."""

from __future__ import annotations

import pytest

from shiro.domain.voice.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, HotkeyError, parse_hotkey


def test_parse_hotkey() -> None:
    talk = parse_hotkey("ctrl+alt+space")
    assert (talk.modifiers, talk.key) == (MOD_CONTROL | MOD_ALT, 0x20)
    stop = parse_hotkey("Ctrl + Alt + Shift + S")
    assert (stop.modifiers, stop.key) == (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("S"))
    assert parse_hotkey("alt+f9").key == 0x78
    for bad in ("", "space", "ctrl+hyper+x", "ctrl+çç"):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)
