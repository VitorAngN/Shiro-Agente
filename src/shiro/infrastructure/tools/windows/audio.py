"""Volume geral do Windows via Core Audio (pycaw).

As chamadas COM rodam numa thread dedicada, inicializada com ``CoInitialize``,
para não travar o loop do asyncio.
"""

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def _co_initialize() -> None:
    if sys.platform == "win32":
        import comtypes

        comtypes.CoInitialize()


def _endpoint() -> Any:
    if sys.platform != "win32":
        msg = "controle de volume disponível só no Windows"
        raise RuntimeError(msg)
    from pycaw.pycaw import AudioUtilities

    speakers = AudioUtilities.GetSpeakers()
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:  # pycaw recente
        return endpoint
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


class WindowsVolume:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="shiro-audio", initializer=_co_initialize
        )

    async def get_level(self) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._get)

    async def set_level(self, level: int) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._set, level)

    @staticmethod
    def _get() -> int:
        return round(float(_endpoint().GetMasterVolumeLevelScalar()) * 100)

    @staticmethod
    def _set(level: int) -> None:
        endpoint = _endpoint()
        endpoint.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100, None)
        if level > 0:
            endpoint.SetMute(0, None)

    def close(self) -> None:
        self._executor.shutdown(wait=False)
