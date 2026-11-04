"""Clima atual e do dia (R0), via Open-Meteo, que é gratuito e sem chave.

Ordem para decidir o lugar: a cidade dita no pedido, a cidade do ``shiro.toml``
e, por fim, a localização detectada automaticamente (ADR-0013).

Privacidade: o nome da cidade ou as coordenadas são enviados ao Open-Meteo. O
resultado é marcado como ``local_only``: a localização não vai para a nuvem.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args, br_number, expect
from shiro.infrastructure.tools.location import Locator

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Códigos WMO usados pelo Open-Meteo.
WEATHER_CODES: dict[int, str] = {
    0: "céu limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina com geada",
    51: "garoa fraca",
    53: "garoa",
    55: "garoa forte",
    56: "garoa congelante",
    57: "garoa congelante forte",
    61: "chuva fraca",
    63: "chuva moderada",
    65: "chuva forte",
    66: "chuva congelante",
    67: "chuva congelante forte",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "grãos de neve",
    80: "pancadas de chuva fracas",
    81: "pancadas de chuva",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve",
    86: "pancadas de neve fortes",
    95: "trovoadas",
    96: "trovoadas com granizo",
    99: "trovoadas com granizo forte",
}


class WeatherArgs(Args):
    city: str | None = Field(
        default=None, description="Cidade. Omita para usar a cidade configurada."
    )


class WeatherTool:
    def __init__(
        self, http: httpx.AsyncClient, default_city: str = "", locator: Locator | None = None
    ) -> None:
        self._http = http
        self._default_city = default_city.strip()
        self._locator = locator
        self._spec = ToolSpec(
            name="get_weather",
            description="Informa o clima atual e a previsão de hoje.",
            args_model=WeatherArgs,
            risk=RiskLevel.R0,
            timeout_s=10.0,
            output_trusted=False,
            local_only=True,
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return "consultar o clima"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        args = expect(args, WeatherArgs)
        city = (args.city or self._default_city).strip()
        try:
            if city:
                place = await self._geocode(city)
                if place is None:
                    return ToolResult.failure(f"Não encontrei a cidade {city}.")
                name, latitude, longitude = (
                    str(place.get("name", city)),
                    place["latitude"],
                    place["longitude"],
                )
            else:
                detected = await self._locator.locate() if self._locator else None
                if detected is None:
                    return ToolResult.failure(
                        "Não consegui descobrir onde você está. Diga a cidade ou configure "
                        "general.city no shiro.toml."
                    )
                name, latitude, longitude = detected
            forecast = await self._forecast(latitude, longitude)
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return ToolResult.failure("Não consegui consultar o clima agora. Estou sem internet?")
        return _describe(name, forecast)

    async def _geocode(self, city: str) -> dict[str, Any] | None:
        response = await self._http.get(
            GEOCODING_URL, params={"name": city, "count": 1, "language": "pt", "format": "json"}
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    async def _forecast(self, latitude: float, longitude: float) -> dict[str, Any]:
        response = await self._http.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def _describe(place: str, data: dict[str, Any]) -> ToolResult:
    current = data["current"]
    daily = data["daily"]
    sky = WEATHER_CODES.get(int(current["weather_code"]), "tempo indefinido")
    temp = round(float(current["temperature_2m"]))
    feels = round(float(current["apparent_temperature"]))
    humidity = round(float(current["relative_humidity_2m"]))
    low = round(float(daily["temperature_2m_min"][0]))
    high = round(float(daily["temperature_2m_max"][0]))
    rain = daily.get("precipitation_probability_max", [None])[0]
    rain_text = f", chance de chuva de {br_number(float(rain), 0)}%" if rain is not None else ""
    content = (
        f"{place}: {sky}, {temp}°C (sensação de {feels}°C), umidade de {humidity}%. "
        f"Hoje: mínima de {low}°C e máxima de {high}°C{rain_text}."
    )
    say = f"Em {place}, {temp} graus e {sky}. Máxima de {high}{rain_text}."
    return ToolResult.success(content, say=say)
