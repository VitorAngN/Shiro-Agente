"""Tema do terminal: cores só onde dá, NO_COLOR e Windows sem console."""

from __future__ import annotations

import io

import pytest


def test_theme_paints_only_when_enabled() -> None:
    from shiro.interfaces.text.theme import RED, Theme

    plain, colored = Theme(color=False), Theme(color=True)

    assert plain.assistant("Shiro", "Oi.") == "shiro ▸ Oi."
    assert plain.status(True, "auditoria íntegra") == "[ ok ] auditoria íntegra"
    assert plain.status(False, "modo somente leitura") == "[ !! ] modo somente leitura"
    assert "白" in plain.banner("0.1.0") and "\x1b[" not in plain.banner("0.1.0")
    assert colored.paint("x", RED) == "\x1b[38;2;255;46;77mx\x1b[0m"
    assert colored.confirm("Abrir?").endswith("\x1b[0m")


def test_colors_respect_no_color_and_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    import shiro.interfaces.text.theme as theme
    from shiro.interfaces.text.theme import colors_supported

    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    # Um terminal falso não tem console do Windows por trás; o VT é testado à parte.
    monkeypatch.setattr(theme, "_enable_windows_vt", lambda _stream: True)
    assert not colors_supported(io.StringIO())
    monkeypatch.setenv("NO_COLOR", "1")
    assert not colors_supported(Tty())
    monkeypatch.delenv("NO_COLOR")
    assert colors_supported(Tty())


@pytest.mark.windows
def test_windows_vt_fails_safely_without_a_console() -> None:
    from shiro.interfaces.text.theme import _enable_windows_vt  # pyright: ignore[reportPrivateUsage]

    assert _enable_windows_vt(io.StringIO()) is False
