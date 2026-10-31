from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from shiro.core.models import ToolResult
from shiro.core.ports import ToolContext
from shiro.tools.builtin._base import br_number
from shiro.tools.builtin.apps import AppTarget, CloseAppTool, OpenAppTool
from shiro.tools.builtin.audio import ChangeVolumeTool, SetVolumeTool
from shiro.tools.builtin.clock import GetTimeTool
from shiro.tools.builtin.media import MediaAction, MediaControlTool
from shiro.tools.builtin.system import (
    GB,
    Battery,
    GpuUsage,
    PsutilProbe,
    SystemInfoTool,
    Usage,
)
from shiro.tools.builtin.weather import FORECAST_URL, GEOCODING_URL, WeatherTool
from tests.fakes import SAO_PAULO, FixedClock

CTX = ToolContext(trace_id="t", now=FixedClock().now())


async def run(tool: Any, **arguments: Any) -> ToolResult:
    args = tool.spec.args_model.model_validate(arguments)
    result: ToolResult = await tool.run(args, CTX)
    return result


def test_br_number() -> None:
    assert br_number(9.26) == "9,3"
    assert br_number(10.0) == "10"
    assert br_number(23.84) == "23,8"
    assert br_number(39.6, 0) == "40"


async def test_get_time_speaks_portuguese() -> None:
    result = await run(GetTimeTool(SAO_PAULO))
    assert result.say == "São 17h05 de sábado, 31 de outubro."
    assert "2026" in result.content


class FakeVolume:
    def __init__(self, level: int = 50) -> None:
        self.level = level

    async def get_level(self) -> int:
        return self.level

    async def set_level(self, level: int) -> None:
        self.level = level


async def test_volume_tools() -> None:
    volume = FakeVolume(95)

    result = await run(ChangeVolumeTool(volume), delta=10)
    assert volume.level == 100
    assert result.say == "Volume em 100."

    result = await run(SetVolumeTool(volume), level=20)
    assert volume.level == 20
    assert result.say == "Volume em 20."
    assert SetVolumeTool(volume).describe(SetVolumeTool(volume).spec.args_model(level=20)) == (
        "definir o volume em 20%"
    )
    with pytest.raises(ValidationError):
        SetVolumeTool(volume).spec.args_model.model_validate({"level": 101})


async def test_media_control() -> None:
    pressed: list[MediaAction] = []

    class Keys:
        async def press(self, action: MediaAction) -> None:
            pressed.append(action)

    result = await run(MediaControlTool(Keys()), action="next")
    assert pressed == ["next"]
    assert result.say == "Próxima."
    with pytest.raises(ValidationError):
        MediaControlTool(Keys()).spec.args_model.model_validate({"action": "rewind"})


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


async def test_open_app_only_accepts_configured_apps() -> None:
    launcher = FakeLauncher()
    tool = OpenAppTool(APPS, launcher)

    result = await run(tool, app="spotify")
    assert launcher.launched == ["spotify:"]
    assert result.say == "Abrindo o Spotify."

    schema = tool.spec.args_model.model_json_schema()
    assert schema["properties"]["app"]["enum"] == ["spotify", "vscode"]
    with pytest.raises(ValidationError):
        tool.spec.args_model.model_validate({"app": "regedit"})


async def test_close_app() -> None:
    launcher = FakeLauncher(running=1)
    result = await run(CloseAppTool(APPS, launcher), app="spotify")
    assert launcher.closed == ["Spotify.exe"]
    assert result.ok

    not_running = await run(CloseAppTool(APPS, FakeLauncher(running=0)), app="spotify")
    assert not not_running.ok
    assert "não estava aberto" in not_running.content

    unknown_process = await run(CloseAppTool(APPS, FakeLauncher()), app="vscode")
    assert not unknown_process.ok
    assert "process" in unknown_process.content


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


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("cpu", "CPU em 12% de uso."),
        ("ram", "RAM: 9,2 de 23,8 GB em uso (39%)."),
        ("disk", "Disco: 300 de 476 GB em uso (63%)."),
        ("battery", "Bateria em 81%, carregando."),
    ],
)
async def test_system_info(metric: str, expected: str) -> None:
    result = await run(SystemInfoTool(FakeProbe()), metric=metric)
    assert result.content == expected


async def test_system_info_without_gpu() -> None:
    result = await run(SystemInfoTool(FakeProbe()), metric="gpu")
    assert not result.ok


async def test_psutil_probe_reads_this_machine() -> None:
    probe = PsutilProbe()
    memory = await probe.memory()
    assert 0 < memory.used <= memory.total
    disk = await probe.disk()
    assert disk.total > 0


def weather_client(*, found: bool = True) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(GEOCODING_URL):
            assert request.url.params["language"] == "pt"
            results = [{"name": "Curitiba", "latitude": -25.43, "longitude": -49.27}]
            return httpx.Response(200, json={"results": results if found else []})
        assert url.startswith(FORECAST_URL)
        assert request.url.params["latitude"] == "-25.43"
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 17.6,
                    "apparent_temperature": 16.2,
                    "relative_humidity_2m": 81,
                    "weather_code": 3,
                },
                "daily": {
                    "temperature_2m_max": [22.4],
                    "temperature_2m_min": [13.1],
                    "precipitation_probability_max": [40],
                },
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_weather_uses_default_city() -> None:
    tool = WeatherTool(weather_client(), default_city="Curitiba")
    result = await run(tool)
    assert result.ok
    assert result.say == "Em Curitiba, 18 graus e nublado. Máxima de 22, chance de chuva de 40%."
    assert not tool.spec.output_trusted


async def test_weather_errors_are_friendly() -> None:
    no_city = await run(WeatherTool(weather_client()))
    assert "Não sei de qual cidade" in no_city.content

    unknown = await run(WeatherTool(weather_client(found=False)), city="Xyzópolis")
    assert unknown.content == "Não encontrei a cidade Xyzópolis."

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    tool = WeatherTool(httpx.AsyncClient(transport=httpx.MockTransport(offline)), "Curitiba")
    assert "sem internet" in (await run(tool)).content
