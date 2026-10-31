"""Identidade visual no terminal (ADR-0012, ``docs/08-identidade.md``).

Cores ANSI em 24 bits, com a paleta da SHIRO. Sem cor quando a saída não é um
terminal ou quando ``NO_COLOR`` está definida (https://no-color.org).
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

RED = (255, 46, 77)  # identidade e microfone ativo
CYAN = (52, 228, 240)  # sistema ok
AMBER = (255, 210, 63)  # pede confirmação
WHITE = (238, 241, 246)  # texto principal
GRAY = (154, 163, 178)  # texto secundário
DIM = (125, 134, 152)  # diagnóstico

BANNER = """\
███████╗██╗  ██╗██╗██████╗  ██████╗
██╔════╝██║  ██║██║██╔══██╗██╔═══██╗
███████╗███████║██║██████╔╝██║   ██║
╚════██║██╔══██║██║██╔══██╗██║   ██║
███████║██║  ██║██║██║  ██║╚██████╔╝
╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝"""

ARROW = "▸"

type Color = tuple[int, int, int]


def _enable_windows_vt(stream: TextIO) -> bool:
    """Liga o processamento de sequências ANSI no console do Windows."""
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_virtual_terminal_processing = 0x0004
        return bool(
            kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing)
        )
    except (OSError, ValueError, AttributeError):
        return False


def colors_supported(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    isatty = getattr(stream, "isatty", None)
    if isatty is None or not isatty():
        return False
    return _enable_windows_vt(stream)


class Theme:
    def __init__(self, *, color: bool) -> None:
        self.color = color

    @classmethod
    def for_stream(cls, stream: TextIO) -> Theme:
        return cls(color=colors_supported(stream))

    def paint(self, text: str, rgb: Color, *, bold: bool = False) -> str:
        if not self.color:
            return text
        weight = "1;" if bold else ""
        return f"\x1b[{weight}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\x1b[0m"

    def user_prompt(self) -> str:
        return self.paint(f"você {ARROW} ", GRAY)

    def assistant(self, name: str, text: str) -> str:
        return f"{self.paint(f'{name.casefold()} {ARROW}', RED, bold=True)} {text}"

    def meta(self, text: str) -> str:
        return self.paint(f"  {text}", DIM)

    def confirm(self, prompt: str) -> str:
        return self.paint(f"  ⚠ {prompt} [s/N] ", AMBER)

    def status(self, ok: bool, text: str) -> str:
        tag = self.paint("[ ok ]", CYAN) if ok else self.paint("[ !! ]", AMBER)
        return f"{tag} {text}"

    def banner(self, version: str) -> str:
        art = self.paint(BANNER, WHITE, bold=True)
        kanji = self.paint("白", RED, bold=True)
        tagline = f"{kanji} {self.paint(f'// シロ · assistente local · v{version}', GRAY)}"
        return f"{art}\n{tagline}"
