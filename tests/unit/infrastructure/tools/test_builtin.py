"""Ferramentas nativas com dublês do PC: hora, volume, mídia, apps, sistema e clima."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from shiro.domain.models import ToolResult
from shiro.infrastructure.tools._base import br_number
from shiro.infrastructure.tools.apps import CloseAppTool, OpenAppTool
from shiro.infrastructure.tools.audio import ChangeVolumeTool, SetVolumeTool
from shiro.infrastructure.tools.clock import GetTimeTool
from shiro.infrastructure.tools.location import CACHE_TTL_S, GEOJS_URL, IpLocator, Place
from shiro.infrastructure.tools.media import MediaAction, MediaControlTool
from shiro.infrastructure.tools.system import (
    PsutilProbe,
    SystemInfoTool,
)
from shiro.infrastructure.tools.weather import FORECAST_URL, GEOCODING_URL, WeatherTool
from tests.fakes.agent import SAO_PAULO
from tests.fakes.desktop import APPS, CTX, FakeLauncher, FakeProbe, FakeVolume


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
    assert "Não consegui descobrir onde você está" in no_city.content

    unknown = await run(WeatherTool(weather_client(found=False)), city="Xyzópolis")
    assert unknown.content == "Não encontrei a cidade Xyzópolis."

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    tool = WeatherTool(httpx.AsyncClient(transport=httpx.MockTransport(offline)), "Curitiba")
    assert "sem internet" in (await run(tool)).content


class FixedLocator:
    def __init__(self, place: Place | None) -> None:
        self.place = place
        self.calls = 0

    async def locate(self) -> Place | None:
        self.calls += 1
        return self.place


async def test_weather_uses_detected_location_when_no_city() -> None:
    locator = FixedLocator(Place("Curitiba", -25.43, -49.27))
    tool = WeatherTool(weather_client(), locator=locator)

    result = await run(tool)

    assert result.ok
    assert result.say is not None and result.say.startswith("Em Curitiba, 18 graus")
    assert locator.calls == 1
    assert tool.spec.local_only


async def test_explicit_city_wins_over_detection() -> None:
    locator = FixedLocator(Place("Outra", 0.0, 0.0))
    result = await run(WeatherTool(weather_client(), locator=locator), city="Curitiba")
    assert result.ok
    assert locator.calls == 0


def geojs_client(payload: dict[str, Any] | None, calls: list[int]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == GEOJS_URL
        calls.append(1)
        if payload is None:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


GEOJS = {
    "city": "Curitiba",
    "region": "Paraná",
    "latitude": "-25.4284",
    "longitude": "-49.2733",
    "timezone": "America/Sao_Paulo",
}


async def test_ip_locator_detects_and_caches(tmp_path: Path) -> None:
    calls: list[int] = []
    now = [1_000_000.0]
    cache = tmp_path / "location.json"
    locator = IpLocator(geojs_client(GEOJS, calls), cache, clock=lambda: now[0])

    place = await locator.locate()
    assert place == Place("Curitiba", -25.4284, -49.2733)
    assert cache.is_file()

    assert await locator.locate() == place  # do cache
    assert len(calls) == 1

    now[0] += CACHE_TTL_S + 1  # cache vencido: consulta de novo
    await locator.locate()
    assert len(calls) == 2


async def test_ip_locator_failures_return_none(tmp_path: Path) -> None:
    offline = IpLocator(geojs_client(None, []), tmp_path / "a.json")
    assert await offline.locate() is None

    nameless = IpLocator(geojs_client({**GEOJS, "city": "", "region": ""}, []), None)
    assert await nameless.locate() is None

    broken_cache = tmp_path / "b.json"
    broken_cache.write_text("{não é json", encoding="utf-8")
    recovered = IpLocator(geojs_client(GEOJS, []), broken_cache)
    assert (await recovered.locate()) is not None
