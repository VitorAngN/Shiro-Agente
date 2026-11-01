"""A SHIRO na bandeja: o modo "sempre ligado" (Fase 2).

* ``shiro-tray`` (sem console; é o que o início com o Windows chama);
* ``shiro tray`` (com console, para ver o que acontece).

Ao iniciar: instância única, modelos carregados, atalhos globais, palavra de
ativação (se ligada) e o resumo do dia numa notificação (RF-39).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any, TextIO, cast

from shiro import autostart, paths
from shiro.activities.service import ActivityService
from shiro.interfaces.dialogs import DialogConfirmation
from shiro.interfaces.theme import Theme
from shiro.interfaces.tray import LogStream, TrayController
from shiro.interfaces.voice import Trigger
from shiro.settings import ConfigError, Settings, load_settings
from shiro.voice_app import VoiceRuntime, build_voice_runtime

log = logging.getLogger(__name__)


async def day_summary(service: ActivityService) -> str:
    """Resumo para a notificação de bom-dia: o que vence hoje e o que está atrasado."""
    today = (await service.list("today")).say or ""
    overdue = await service.list("overdue")
    parts = [today]
    if overdue.ok and overdue.say and not overdue.say.startswith(("Nada", "Nenhuma")):
        parts.append(overdue.say)
    return " ".join(p for p in parts if p)


class RuntimeActions:
    """Ações do menu da bandeja sobre a sessão de voz em execução."""

    def __init__(self, runtime: VoiceRuntime, tray: TrayController) -> None:
        self._runtime = runtime
        self._tray = tray

    def talk(self) -> None:
        self._runtime.triggers.put(Trigger("talk"))

    def stop(self) -> None:
        self._runtime.triggers.put(Trigger("stop"))

    def wake_active(self) -> bool:
        return self._runtime.wake_active

    async def toggle_wake(self) -> None:
        runtime = self._runtime
        if runtime.wake is None:
            await runtime.start_wake(lambda ok, text: log.info("bandeja: %s", text))
        else:
            runtime.pause_wake(runtime.wake_active)
        self._tray.paused = not runtime.wake_active
        self._tray.refresh()

    async def release_gpu(self) -> None:
        release = getattr(self._runtime.app.local_llm, "release", None)
        if release is None:
            return
        await release()
        await self._tray.notify("SHIRO", "GPU liberada. O modelo volta no próximo pedido.")

    def autostart_enabled(self) -> bool:
        return autostart.status() is not None

    async def toggle_autostart(self) -> None:
        if await asyncio.to_thread(autostart.status) is not None:
            await asyncio.to_thread(autostart.disable)
            await self._tray.notify("SHIRO", "Não vou mais iniciar com o Windows.")
        else:
            how = await asyncio.to_thread(autostart.enable)
            await self._tray.notify("SHIRO", f"Vou iniciar com o Windows ({how}).")

    def open_logs(self) -> None:
        folder = paths.log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        startfile: Any = getattr(os, "startfile", None)
        if startfile is not None:
            startfile(folder)

    def quit(self) -> None:
        self._runtime.triggers.put(Trigger("quit"))


async def run_tray(settings: Settings) -> int:
    loop = asyncio.get_running_loop()
    tray = TrayController(name=settings.general.assistant_name, loop=loop)
    try:
        runtime = await build_voice_runtime(
            settings,
            keyboard=DialogConfirmation(),
            theme=Theme(color=False),
            out=cast(TextIO, LogStream()),
            on_phase=tray.set_phase,
            extra_notifier=tray,
        )
    except Exception as exc:
        log.exception("a bandeja não iniciou")
        _alert(f"A SHIRO não conseguiu iniciar:\n\n{exc}")
        return 1
    tray.start(RuntimeActions(runtime, tray))
    problems: list[str] = []

    def report(ok: bool, text: str) -> None:
        log.info("bandeja: %s%s", "" if ok else "PROBLEMA: ", text)
        if not ok:
            problems.append(text)

    try:
        await runtime.start(report)
        tray.paused = not runtime.wake_active
        tray.refresh()
        if problems:
            await tray.notify("SHIRO com limitações", " · ".join(problems)[:250])
        if runtime.app.activities is not None:
            summary = await day_summary(runtime.app.activities)
            await tray.notify("SHIRO online", summary or "Pronta.")
        await runtime.session.run(runtime.triggers)
    finally:
        tray.stop()
        await runtime.aclose()
    return 0


def _alert(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "SHIRO", 0x10)  # type: ignore[attr-defined]
    elif sys.stderr is not None:
        print(message, file=sys.stderr)  # noqa: T201


def main() -> int:
    from shiro.observability.logging import configure_logging
    from shiro.singleton import AlreadyRunningError, single_instance

    try:
        settings = load_settings()
    except ConfigError as exc:
        _alert(f"Configuração inválida:\n\n{exc}")
        return 1
    configure_logging(settings.logging, paths.log_dir(), console=False)
    try:
        lock = single_instance()
    except AlreadyRunningError as exc:
        _alert(str(exc).capitalize() + ".")
        return 1
    try:
        with contextlib.suppress(KeyboardInterrupt):
            return asyncio.run(run_tray(settings))
        return 130
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
