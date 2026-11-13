"""Controle do PC no Windows: navegador, teclado (``SendInput``), mouse e UI Automation.

A "janela em uso" é a que está na frente, a não ser que seja a própria SHIRO
(quem clicou no microfone do programa): aí vale a próxima janela visível.
Antes de digitar ou clicar, essa janela volta para a frente.

Os nomes dos botões vêm do UI Automation (o mesmo que os leitores de tela
usam), pelo pacote ``uiautomation``. O Chrome, o Edge e os apps do Windows
expõem os elementos por ele, inclusive os links das páginas.
"""

from __future__ import annotations

import asyncio
import ctypes
import importlib
import os
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from shiro.infrastructure.tools.control import Browser, MouseButton, Screen, ScreenElement

OWN_TITLES = frozenset({"SHIRO"})
_SKIP_CLASSES = frozenset({"Shell_TrayWnd", "Progman", "WorkerW", "Shell_SecondaryTrayWnd"})
_BROWSER_EXES: dict[str, str] = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "opera": "opera.exe",
}
_KINDS: dict[str, str] = {
    "ButtonControl": "botão",
    "SplitButtonControl": "botão",
    "HyperlinkControl": "link",
    "MenuItemControl": "item de menu",
    "TabItemControl": "aba",
    "EditControl": "campo",
    "ComboBoxControl": "lista",
    "CheckBoxControl": "caixa de seleção",
    "RadioButtonControl": "opção",
    "ListItemControl": "item",
    "TreeItemControl": "item",
    "DataItemControl": "item",
    "TextControl": "texto",
}
_MAX_NODES = 2500
_MAX_ELEMENTS = 400
_WALK_BUDGET_S = 6.0

_VK: dict[str, int] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "enter": 0x0D,
    "esc": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "printscreen": 0x2C,
    "capslock": 0x14,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
}
_EXTENDED = frozenset({0x2E, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x5B})
_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_KEYEVENTF_EXTENDEDKEY, _KEYEVENTF_KEYUP, _KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
_MOUSE_FLAGS: dict[str, tuple[int, int]] = {"esquerdo": (0x2, 0x4), "direito": (0x8, 0x10)}
_GW_HWNDNEXT = 2
_DWMWA_CLOAKED = 14


def _require_windows() -> None:
    if sys.platform != "win32":
        msg = "controle do PC disponível só no Windows"
        raise RuntimeError(msg)


# --- estruturas do SendInput (tamanhos do Windows 64 bits) ------------------


class _KeybdInput(ctypes.Structure):
    _fields_ = (
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("ki", _KeybdInput), ("mi", _MouseInput))


class _Input(ctypes.Structure):
    _fields_ = (("type", ctypes.c_uint32), ("u", _InputUnion))


def _key_input(vk: int, scan: int, flags: int) -> _Input:
    event = _Input(type=_INPUT_KEYBOARD)
    event.u.ki = _KeybdInput(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return event


def _mouse_input(flags: int) -> _Input:
    event = _Input(type=_INPUT_MOUSE)
    event.u.mi = _MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return event


def _send(events: Sequence[_Input]) -> None:
    _require_windows()
    array = (_Input * len(events))(*events)
    user32: Any = ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]
    user32.SendInput(len(events), array, ctypes.sizeof(_Input))


def _vk_of(key: str) -> int:
    if key in _VK:
        return _VK[key]
    return ord(key.upper())  # letras e números: o código é o próprio caractere


def unicode_events(text: str) -> list[_Input]:
    """Cada caractere vira descer/subir com ``KEYEVENTF_UNICODE`` (acentos, emoji...)."""
    events: list[_Input] = []
    for char in text.replace("\r\n", "\n"):
        if char == "\n":
            events += [_key_input(0x0D, 0, 0), _key_input(0x0D, 0, _KEYEVENTF_KEYUP)]
            continue
        data = char.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i : i + 2], "little")
            events.append(_key_input(0, unit, _KEYEVENTF_UNICODE))
            events.append(_key_input(0, unit, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    return events


def combo_events(keys: Sequence[str]) -> list[_Input]:
    down: list[_Input] = []
    up: list[_Input] = []
    for key in keys:
        vk = _vk_of(key)
        extended = _KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0
        down.append(_key_input(vk, 0, extended))
        up.insert(0, _key_input(vk, 0, extended | _KEYEVENTF_KEYUP))
    return down + up


# --- janelas ----------------------------------------------------------------


def _user32() -> Any:
    _require_windows()
    return ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]


def _title(hwnd: int) -> str:
    user32 = _user32()
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def _class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _cloaked(hwnd: int) -> bool:
    try:
        dwmapi: Any = ctypes.windll.dwmapi  # pyright: ignore[reportAttributeAccessIssue]
    except OSError:
        return False
    value = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return value.value != 0


def usable_window(hwnd: int, *, minimized: bool = False) -> bool:
    """Janela de verdade do usuário: visível, com título, fora a SHIRO e a barra de tarefas."""
    user32 = _user32()
    if not user32.IsWindowVisible(hwnd) or (user32.IsIconic(hwnd) and not minimized):
        return False
    title = _title(hwnd)
    return (
        bool(title)
        and title not in OWN_TITLES
        and _class(hwnd) not in _SKIP_CLASSES
        and not (_cloaked(hwnd))
    )


def target_window() -> int:
    """A janela da frente, pulando a da SHIRO e as invisíveis; 0 se não houver."""
    user32 = _user32()
    user32.GetWindow.restype = ctypes.c_void_p
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = int(user32.GetForegroundWindow() or 0)
    for _ in range(200):
        if not hwnd or usable_window(hwnd):
            return hwnd
        hwnd = int(user32.GetWindow(ctypes.c_void_p(hwnd), _GW_HWNDNEXT) or 0)
    return 0


def bring_forward(hwnd: int) -> None:
    """Traz a janela para a frente. O Alt "falso" libera o ``SetForegroundWindow``."""
    user32 = _user32()
    if not hwnd or int(user32.GetForegroundWindow() or 0) == hwnd:
        return
    _send(combo_events(("alt",)))
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    time.sleep(0.15)


# --- UI Automation ----------------------------------------------------------


def _automation() -> Any:
    return importlib.import_module("uiautomation")


def _walk(auto: Any, root: Any) -> Iterator[Any]:
    deadline = time.monotonic() + _WALK_BUDGET_S
    for count, (control, _depth) in enumerate(auto.WalkControl(root, False, 40)):
        if count >= _MAX_NODES or time.monotonic() > deadline:
            return
        yield control


def read_screen() -> Screen:
    _require_windows()
    hwnd = target_window()
    if not hwnd:
        return Screen(window="(nenhuma janela)")
    auto = _automation()
    elements: list[ScreenElement] = []
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        for control in _walk(auto, root):
            kind = _KINDS.get(str(control.ControlTypeName))
            name = str(control.Name or "").strip()
            if kind is None or not name or len(name) > 150:
                continue
            try:
                if control.IsOffscreen:
                    continue
                rect = control.BoundingRectangle
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                elements.append(ScreenElement(name, kind, rect.xcenter(), rect.ycenter()))
            except Exception:  # noqa: S112 - elemento sumiu no meio da leitura
                continue
            if len(elements) >= _MAX_ELEMENTS:
                break
    return Screen(window=_title(hwnd), elements=tuple(elements))


def click_at(x: int, y: int, button: MouseButton, *, double: bool) -> None:
    user32 = _user32()
    bring_forward(target_window())
    user32.SetCursorPos(x, y)
    down, up = _MOUSE_FLAGS[button]
    clicks = [_mouse_input(down), _mouse_input(up)]
    _send(clicks * (2 if double else 1))


def type_into_window(text: str) -> None:
    bring_forward(target_window())
    events = unicode_events(text)
    for start in range(0, len(events), 200):  # em pedaços: apps lentos perdem teclas
        _send(events[start : start + 200])
        time.sleep(0.01)


def press_into_window(keys: Sequence[str]) -> None:
    bring_forward(target_window())
    _send(combo_events(keys))


# --- navegador --------------------------------------------------------------


def browser_path(browser: str) -> str | None:
    """Caminho do navegador pelo registro (App Paths), onde os instaladores se anunciam."""
    if sys.platform != "win32":
        return None
    import winreg

    exe = _BROWSER_EXES[browser]
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value = str(winreg.QueryValueEx(key, "")[0]).strip('"')
        except OSError:
            continue
        if value and Path(value).exists():
            return value
    return None


def open_in_browser(url: str, browser: Browser) -> None:
    if sys.platform != "win32":
        msg = "abrir sites disponível só no Windows"
        raise RuntimeError(msg)
    if browser != "padrao":
        path = browser_path(browser)
        if path is not None:
            subprocess.Popen([path, url], close_fds=True)  # noqa: S603 - executável do registro
            return
    os.startfile(url)  # noqa: S606 - url já validada (só http/https)


class WindowsDesktopControl:
    async def open_url(self, url: str, browser: Browser) -> None:
        await asyncio.to_thread(open_in_browser, url, browser)

    async def type_text(self, text: str) -> None:
        await asyncio.to_thread(type_into_window, text)

    async def press_keys(self, keys: Sequence[str]) -> None:
        await asyncio.to_thread(press_into_window, tuple(keys))

    async def screen(self) -> Screen:
        return await asyncio.to_thread(read_screen)

    async def click(self, x: int, y: int, *, button: MouseButton, double: bool) -> None:
        await asyncio.to_thread(click_at, x, y, button, double=double)


def enable_dpi_awareness() -> None:
    """Coordenadas do UI Automation e do mouse na mesma escala (telas com zoom)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # pyright: ignore[reportAttributeAccessIssue]
    except (AttributeError, OSError):
        return
