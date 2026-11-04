"""Confirmação física fora do terminal (bandeja): caixa de diálogo do Windows.

Ações R3 nunca são confirmadas por voz (ADR-0015); na bandeja não há teclado
de terminal, então a confirmação é um clique numa janela "Sim/Não" com o
"Não" como padrão.
"""

from __future__ import annotations

import asyncio
import sys

from shiro.domain.models import DecisionKind

_MB_YESNO = 0x04
_MB_ICONWARNING = 0x30
_MB_DEFBUTTON2 = 0x100
_MB_SETFOREGROUND = 0x10000
_MB_TOPMOST = 0x40000
_IDYES = 6


def _message_box(text: str, title: str) -> bool:
    import ctypes

    flags = _MB_YESNO | _MB_ICONWARNING | _MB_DEFBUTTON2 | _MB_SETFOREGROUND | _MB_TOPMOST
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags) == _IDYES  # type: ignore[attr-defined]


class DialogConfirmation:
    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        if sys.platform != "win32":
            return False  # sem como confirmar fisicamente: na dúvida, não
        label = "Ação sensível" if kind is DecisionKind.CONFIRM_PHYSICAL else "Confirmação"
        return await asyncio.to_thread(_message_box, f"{prompt}\n\nConfirmar?", f"SHIRO · {label}")
