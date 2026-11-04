"""Atalhos de teclado: "ctrl+alt+space" → modificadores e tecla virtual do Windows."""

from __future__ import annotations

from dataclasses import dataclass

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}
_KEYS = {
    "space": 0x20,
    "espaco": 0x20,
    "enter": 0x0D,
    "esc": 0x1B,
    "tab": 0x09,
    "pause": 0x13,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    text: str
    modifiers: int
    key: int


def parse_hotkey(text: str) -> Hotkey:
    """Converte "ctrl+alt+space" para os códigos do ``RegisterHotKey``."""
    parts = [p.strip().casefold() for p in text.split("+") if p.strip()]
    if not parts:
        msg = "atalho vazio"
        raise HotkeyError(msg)
    *mods, key = parts
    modifiers = 0
    for mod in mods:
        if mod not in _MODIFIERS:
            msg = f'modificador desconhecido "{mod}" em "{text}"'
            raise HotkeyError(msg)
        modifiers |= _MODIFIERS[mod]
    if not modifiers:
        msg = (
            f'"{text}" precisa de ctrl, alt, shift ou win: atalho global sem modificador atrapalha'
        )
        raise HotkeyError(msg)
    if key in _KEYS:
        code = _KEYS[key]
    elif len(key) == 1 and key.isalnum() and key.isascii():
        code = ord(key.upper())
    else:
        msg = f'tecla desconhecida "{key}" em "{text}"'
        raise HotkeyError(msg)
    return Hotkey(text=text, modifiers=modifiers, key=code)
