"""Bandeja: ícones, menu no laço do asyncio, ações e resumo do dia."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from shiro.application.activities.service import ActivityService
from shiro.infrastructure.persistence.activities import SqliteActivityStore, SqliteJobStore
from shiro.infrastructure.persistence.database import Database
from shiro.interfaces.tray.controller import LogStream, MenuEntry, TrayController, menu_entries
from shiro.interfaces.tray.icons import COLORS, PAUSED, icon_image, tooltip
from shiro.interfaces.tray.main import RuntimeActions, day_summary
from shiro.interfaces.voice.session import Phase, TriggerSource
from tests.fakes.agent import SAO_PAULO
from tests.fakes.voice import until


def test_icons_follow_the_palette() -> None:
    for phase, color in COLORS.items():
        image = icon_image(phase, size=64)
        assert image.size == (64, 64)
        assert image.getpixel((32, 32)) == color  # o visor no centro
    assert icon_image(Phase.IDLE, paused=True).getpixel((32, 32)) == PAUSED
    assert icon_image(Phase.LISTENING, paused=True).getpixel((32, 32)) == COLORS[Phase.LISTENING]
    assert tooltip("Shiro", Phase.THINKING) == "Shiro: pensando"
    assert tooltip("Shiro", Phase.IDLE, paused=True) == "Shiro: escuta pausada"


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.wake = False

    def talk(self) -> None:
        self.calls.append("talk")

    def stop(self) -> None:
        self.calls.append("stop")

    async def toggle_wake(self) -> None:
        self.wake = not self.wake
        self.calls.append("wake")

    def wake_active(self) -> bool:
        return self.wake

    async def release_gpu(self) -> None:
        self.calls.append("gpu")

    async def toggle_autostart(self) -> None:
        self.calls.append("autostart")

    def autostart_enabled(self) -> bool:
        return False

    async def open_dashboard(self) -> None:
        self.calls.append("dashboard")

    def open_logs(self) -> None:
        self.calls.append("logs")

    def quit(self) -> None:
        self.calls.append("quit")


async def test_tray_menu_runs_actions_on_the_event_loop() -> None:
    actions = FakeActions()
    entries = menu_entries(actions)
    labels = [e.label if e else "---" for e in entries]
    assert labels[0] == "Falar agora" and labels[-1] == "Sair"
    assert [e.label for e in entries if e and e.default] == ["Falar agora"]
    tray = TrayController(name="Shiro", loop=asyncio.get_running_loop())

    def press(label: str) -> None:
        entry = next(e for e in entries if e and e.label.startswith(label))
        # O pystray chama de outra thread; o controlador leva para o laço do asyncio.
        asyncio.get_running_loop().run_in_executor(None, tray.dispatch, entry)

    press("Falar")
    press("Ouvir")
    press("Liberar")
    await until(lambda: len(actions.calls) == 3)
    wake = next(e for e in entries if isinstance(e, MenuEntry) and e.checked is not None)
    assert wake.checked is not None and wake.checked()
    assert sorted(actions.calls) == ["gpu", "talk", "wake"]
    tray.set_phase(Phase.SPEAKING)  # sem ícone criado: não faz nada
    await tray.notify("t", "m")
    tray.stop()


def test_log_stream(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="shiro.interfaces.tray.controller"):
        print("shiro ▸ Volume em 20%.\n\n", file=LogStream())
    assert "voz: shiro ▸ Volume em 20%." in caplog.text


class FakeRuntime:
    def __init__(self) -> None:
        self.triggers = TriggerSource()
        self.wake: Any = None
        self.started: list[str] = []
        self.app = type("A", (), {"local_llm": object()})()

    @property
    def wake_active(self) -> bool:
        return self.wake is not None and self.wake.enabled

    async def start_wake(self, report: Callable[[bool, str], None]) -> None:
        self.wake = type("W", (), {"enabled": True})()
        report(True, "ok")

    def pause_wake(self, paused: bool) -> None:
        self.wake.enabled = not paused


async def test_runtime_actions() -> None:
    runtime = FakeRuntime()
    tray = TrayController(name="Shiro", loop=asyncio.get_running_loop())
    actions = RuntimeActions(runtime, tray)  # type: ignore[arg-type]
    actions.talk()
    actions.stop()
    actions.quit()
    got = [await runtime.triggers.next() for _ in range(3)]
    assert [t.kind for t in got] == ["talk", "stop", "quit"]

    await actions.toggle_wake()  # liga pela primeira vez
    assert actions.wake_active() and not tray.paused
    await actions.toggle_wake()  # pausa
    assert not actions.wake_active() and tray.paused
    await actions.release_gpu()  # modelo sem "release": nada a fazer


async def test_day_summary() -> None:
    from tests.fakes.clock import MovableClock

    database = await Database.open(":memory:")
    clock = MovableClock(datetime(2026, 11, 4, 8, 0, tzinfo=SAO_PAULO))
    service = ActivityService(
        store=SqliteActivityStore(database), jobs=SqliteJobStore(database), clock=clock
    )
    assert await day_summary(service) == "Nada para hoje."
    await service.create("prova de física", "hoje às 19h", None)
    summary = await day_summary(service)
    assert "prova de física" in summary
    await database.close()
