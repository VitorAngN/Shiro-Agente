"""Voz do Windows pelo SAPI 5 (ex.: "Microsoft Maria Desktop", pt-BR), sem download.

O áudio é renderizado em memória (``SpMemoryStream``) e tocado pelo mesmo
player do Kokoro, para o atalho de parar funcionar igual nos dois motores. O
COM exige uma thread própria, inicializada para ele.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from shiro.domain.voice.audio import Audio

_SAFT_22KHZ_16BIT_MONO = 22
_RATE = 22_050


def _init_com() -> None:
    import comtypes  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

    comtypes.CoInitialize()


class SapiTTS:
    def __init__(self, *, voice_hint: str = "Maria", speed: float = 1.0) -> None:
        self._hint = voice_hint.casefold()
        self._rate = max(-10, min(10, round((speed - 1.0) * 10)))
        self._executor = ThreadPoolExecutor(max_workers=1, initializer=_init_com)
        self._voice: Any = None
        self.voice_name = ""

    @property
    def name(self) -> str:
        return f"sapi/{self.voice_name or self._hint}"

    async def synthesize(self, text: str) -> Audio:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._render, text)

    def _render(self, text: str) -> Audio:
        import comtypes.client  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

        if self._voice is None:
            voice: Any = comtypes.client.CreateObject("SAPI.SpVoice")  # pyright: ignore[reportUnknownMemberType]
            tokens = voice.GetVoices()
            for i in range(tokens.Count):
                token = tokens.Item(i)
                description = str(token.GetDescription())
                if self._hint in description.casefold():
                    voice.Voice = token
                    self.voice_name = description
                    break
            voice.Rate = self._rate
            self._voice = voice
        stream: Any = comtypes.client.CreateObject("SAPI.SpMemoryStream")  # pyright: ignore[reportUnknownMemberType]
        audio_format = stream.Format
        audio_format.Type = _SAFT_22KHZ_16BIT_MONO
        stream.Format = audio_format
        self._voice.AudioOutputStream = stream
        self._voice.Speak(text, 0)
        data = stream.GetData()
        raw = (
            bytes(data)
            if isinstance(data, bytes | bytearray | memoryview)
            else bytes(bytearray(data))
        )
        return Audio.from_pcm16(raw, _RATE)

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
