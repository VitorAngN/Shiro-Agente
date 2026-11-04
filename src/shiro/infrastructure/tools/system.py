"""Uso de recursos do PC (R0): CPU, RAM, GPU, disco e bateria."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal, NamedTuple, Protocol

import psutil
from pydantic import BaseModel, Field

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args, br_number, expect

Metric = Literal["cpu", "ram", "gpu", "disk", "battery"]
GB = 1024**3


class Usage(NamedTuple):
    used: float
    total: float


class GpuUsage(NamedTuple):
    used_mb: int
    total_mb: int
    utilization: int


class Battery(NamedTuple):
    percent: float
    plugged: bool


class SystemProbe(Protocol):
    async def cpu_percent(self) -> float: ...
    async def memory(self) -> Usage: ...
    async def disk(self) -> Usage: ...
    async def battery(self) -> Battery | None: ...
    async def gpu(self) -> GpuUsage | None: ...


class PsutilProbe:
    """Leitura real via psutil e, para GPU NVIDIA, ``nvidia-smi``."""

    async def cpu_percent(self) -> float:
        return await asyncio.to_thread(psutil.cpu_percent, 0.3)

    async def memory(self) -> Usage:
        mem = psutil.virtual_memory()
        return Usage(float(mem.total - mem.available), float(mem.total))

    async def disk(self) -> Usage:
        usage = psutil.disk_usage(Path.home().anchor)
        return Usage(float(usage.used), float(usage.total))

    async def battery(self) -> Battery | None:
        info = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        return Battery(float(info.percent), bool(info.power_plugged)) if info else None

    async def gpu(self) -> GpuUsage | None:
        return await asyncio.to_thread(_nvidia_smi)


def _nvidia_smi() -> GpuUsage | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        output = subprocess.run(  # noqa: S603 - executável resolvido e argumentos fixos
            [
                exe,
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
            creationflags=flags,
        ).stdout
        used, total, util = (int(part.strip()) for part in output.splitlines()[0].split(","))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return GpuUsage(used, total, util)


class SystemInfoArgs(Args):
    metric: Metric = Field(description="cpu, ram, gpu, disk (disco) ou battery (bateria)")


class SystemInfoTool:
    def __init__(self, probe: SystemProbe) -> None:
        self._probe = probe
        self._spec = ToolSpec(
            name="system_info",
            description="Informa o uso de recursos do PC: CPU, RAM, GPU, disco ou bateria.",
            args_model=SystemInfoArgs,
            risk=RiskLevel.R0,
            timeout_s=5.0,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return "consultar o uso do sistema"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        args = expect(args, SystemInfoArgs)
        text = await self._read(args.metric)
        if text is None:
            return ToolResult.failure("Essa informação não está disponível neste PC.")
        return ToolResult.success(text, say=text)

    async def _read(self, metric: Metric) -> str | None:
        if metric == "cpu":
            return f"CPU em {br_number(await self._probe.cpu_percent(), 0)}% de uso."
        if metric in ("ram", "disk"):
            usage = await (self._probe.memory() if metric == "ram" else self._probe.disk())
            name = "RAM" if metric == "ram" else "Disco"
            percent = 100 * usage.used / usage.total if usage.total else 0
            return (
                f"{name}: {br_number(usage.used / GB)} de {br_number(usage.total / GB)} GB "
                f"em uso ({br_number(percent, 0)}%)."
            )
        if metric == "gpu":
            gpu = await self._probe.gpu()
            if gpu is None:
                return None
            return (
                f"GPU: {br_number(gpu.used_mb / 1024)} de {br_number(gpu.total_mb / 1024)} GB "
                f"de memória em uso, {gpu.utilization}% de utilização."
            )
        battery = await self._probe.battery()
        if battery is None:
            return None
        state = "carregando" if battery.plugged else "na bateria"
        return f"Bateria em {br_number(battery.percent, 0)}%, {state}."
