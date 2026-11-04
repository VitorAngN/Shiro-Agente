"""Dublês do PC: volume, abrir apps e leitura de CPU, RAM e GPU."""

from __future__ import annotations

from shiro.domain.ports import ToolContext
from shiro.infrastructure.tools.apps import AppTarget
from shiro.infrastructure.tools.system import (
    GB,
    Battery,
    GpuUsage,
    Usage,
)
from tests.fakes.agent import FixedClock

CTX = ToolContext(trace_id="t", now=FixedClock().now())


class FakeVolume:
    def __init__(self, level: int = 50) -> None:
        self.level = level

    async def get_level(self) -> int:
        return self.level

    async def set_level(self, level: int) -> None:
        self.level = level


class FakeLauncher:
    def __init__(self, running: int = 1) -> None:
        self.launched: list[str] = []
        self.closed: list[str] = []
        self.running = running

    async def launch(self, target: str) -> None:
        self.launched.append(target)

    async def close(self, process: str) -> int:
        self.closed.append(process)
        return self.running


APPS = {
    "spotify": AppTarget(key="spotify", label="Spotify", launch="spotify:", process="Spotify.exe"),
    "vscode": AppTarget(key="vscode", label="VS Code", launch="code", process=""),
}


class FakeProbe:
    async def cpu_percent(self) -> float:
        return 12.4

    async def memory(self) -> Usage:
        return Usage(9.2 * GB, 23.8 * GB)

    async def disk(self) -> Usage:
        return Usage(300 * GB, 476 * GB)

    async def battery(self) -> Battery | None:
        return Battery(81, True)

    async def gpu(self) -> GpuUsage | None:
        return None
