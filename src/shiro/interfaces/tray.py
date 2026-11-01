"""Ícone na bandeja do Windows (Fase 2): estado, menu e notificações.

O ``pystray`` roda o próprio laço de mensagens numa thread; cada clique no menu
vira uma chamada agendada no laço do asyncio, onde vive a sessão de voz.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from shiro.interfaces.tray_icons import icon_image, tooltip
from shiro.interfaces.voice import Phase

log = logging.getLogger(__name__)


class TrayActions(Protocol):
    def talk(self) -> None: ...
    def stop(self) -> None: ...
    async def toggle_wake(self) -> None: ...
    def wake_active(self) -> bool: ...
    async def release_gpu(self) -> None: ...
    async def toggle_autostart(self) -> None: ...
    def autostart_enabled(self) -> bool: ...
    async def open_dashboard(self) -> None: ...
    def open_logs(self) -> None: ...
    def quit(self) -> None: ...


@dataclass(frozen=True)
class MenuEntry:
    label: str
    run: Callable[[], Awaitable[None] | None]
    checked: Callable[[], bool] | None = None
    default: bool = False  # clique duplo no ícone


def menu_entries(actions: TrayActions) -> list[MenuEntry | None]:
    """Itens do menu; ``None`` é um separador."""
    return [
        MenuEntry("Falar agora", actions.talk, default=True),
        MenuEntry("Parar", actions.stop),
        None,
        MenuEntry('Ouvir "Ei, Shiro"', actions.toggle_wake, checked=actions.wake_active),
        MenuEntry("Liberar a GPU (modo desempenho)", actions.release_gpu),
        MenuEntry(
            "Iniciar com o Windows", actions.toggle_autostart, checked=actions.autostart_enabled
        ),
        None,
        MenuEntry("Abrir painel", actions.open_dashboard),
        MenuEntry("Abrir registros", actions.open_logs),
        MenuEntry("Sair", actions.quit),
    ]


class TrayController:
    def __init__(self, *, name: str, loop: asyncio.AbstractEventLoop) -> None:
        self._name = name
        self._loop = loop
        self._icon: Any = None
        self._thread: threading.Thread | None = None
        self._phase = Phase.IDLE
        self.paused = False

    def dispatch(self, entry: MenuEntry) -> None:
        """Chamado na thread do ``pystray``: executa a ação no laço do asyncio."""

        def run() -> None:
            outcome = entry.run()
            if outcome is not None:
                task = asyncio.ensure_future(outcome)
                task.add_done_callback(_log_failure)

        self._loop.call_soon_threadsafe(run)

    def start(self, actions: TrayActions) -> None:
        import pystray  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

        items: list[Any] = []
        for entry in menu_entries(actions):
            if entry is None:
                items.append(pystray.Menu.SEPARATOR)  # pyright: ignore[reportUnknownMemberType]
                continue
            checked = (lambda e: lambda _item: e.checked())(entry) if entry.checked else None  # pyright: ignore[reportOptionalCall]
            items.append(
                pystray.MenuItem(  # pyright: ignore[reportUnknownMemberType]
                    entry.label,
                    (lambda e: lambda _icon, _item: self.dispatch(e))(entry),
                    checked=checked,
                    default=entry.default,
                )
            )
        self._icon = pystray.Icon(  # pyright: ignore[reportUnknownMemberType]
            "shiro",
            icon_image(Phase.IDLE),
            tooltip(self._name, Phase.IDLE),
            pystray.Menu(*items),  # pyright: ignore[reportUnknownMemberType]
        )
        self._thread = threading.Thread(target=self._icon.run, name="bandeja", daemon=True)
        self._thread.start()

    def set_phase(self, phase: Phase) -> None:
        self._phase = phase
        self.refresh()

    def refresh(self) -> None:
        if self._icon is None:
            return
        self._icon.icon = icon_image(self._phase, paused=self.paused)
        self._icon.title = tooltip(self._name, self._phase, paused=self.paused)

    async def notify(self, title: str, message: str) -> None:
        """Notificação do Windows (``Notifier``): lembretes, avisos e erros."""
        if self._icon is not None:
            self._icon.notify(message, title)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
        if self._thread is not None:
            self._thread.join(2)


def _log_failure(task: asyncio.Future[Any]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("ação da bandeja falhou", exc_info=task.exception())


class LogStream(io.TextIOBase):
    """Saída da sessão de voz quando não há terminal: vai para o log."""

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                log.info("voz: %s", line.strip())
        return len(text)
