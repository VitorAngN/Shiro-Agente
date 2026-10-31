"""Localização aproximada do PC, para o clima funcionar sem configurar a cidade (ADR-0013).

A detecção usa o IP público via GeoJS (HTTPS, sem chave). A precisão é de
cidade, às vezes da cidade do provedor de internet. O resultado fica em cache
local por 24 horas, na pasta de dados do SHIRO, e nunca vai para o repositório.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

import httpx

GEOJS_URL = "https://get.geojs.io/v1/ip/geo.json"
CACHE_TTL_S = 24 * 60 * 60


class Place(NamedTuple):
    name: str
    latitude: float
    longitude: float


class Locator(Protocol):
    async def locate(self) -> Place | None:
        """Onde o PC está, ou ``None`` se não for possível descobrir."""
        ...


class IpLocator:
    def __init__(
        self,
        http: httpx.AsyncClient,
        cache_file: Path | None,
        *,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._http = http
        self._cache_file = cache_file
        self._ttl_s = ttl_s
        self._clock = clock

    async def locate(self) -> Place | None:
        cached = self._read_cache()
        if cached is not None:
            return cached
        try:
            response = await self._http.get(GEOJS_URL)
            response.raise_for_status()
            data = response.json()
            name = str(data.get("city") or data.get("region") or "").strip()
            place = Place(name, float(data["latitude"]), float(data["longitude"]))
        except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError):
            return None
        if not name:
            return None
        self._write_cache(place)
        return place

    def _read_cache(self) -> Place | None:
        if self._cache_file is None or not self._cache_file.is_file():
            return None
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if self._clock() - float(data["fetched_at"]) > self._ttl_s:
                return None
            return Place(str(data["name"]), float(data["latitude"]), float(data["longitude"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_cache(self, place: Place) -> None:
        if self._cache_file is None:
            return
        payload = {**place._asdict(), "fetched_at": self._clock()}
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return
