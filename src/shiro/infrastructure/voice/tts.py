"""Texto para fala: Kokoro em processo separado e fábrica do motor configurado."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from shiro.config.settings import TTSSettings
from shiro.domain.voice.audio import Audio
from shiro.domain.voice.ports import TextToSpeech
from shiro.infrastructure.voice.models import kokoro_files, kokoro_installed

_CREATE_NO_WINDOW = 0x08000000


class TTSError(RuntimeError):
    pass


class KokoroProcessTTS:
    """Cliente do ``kokoro_worker``: um processo vivo, um pedido por vez."""

    def __init__(
        self,
        *,
        model: Path,
        voices: Path,
        voice: str,
        speed: float = 1.0,
        lang: str = "pt-br",
        command: Sequence[str] | None = None,
        startup_timeout_s: float = 90.0,
        request_timeout_s: float = 60.0,
    ) -> None:
        self._command = (
            list(command)
            if command
            else [
                sys.executable,
                "-m",
                "shiro.infrastructure.voice.kokoro_worker",
                str(model),
                str(voices),
            ]
        )
        self._voice = voice
        self._speed = speed
        self._lang = lang
        self._startup_timeout = startup_timeout_s
        self._request_timeout = request_timeout_s
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.voices: list[str] = []

    @property
    def name(self) -> str:
        return f"kokoro/{self._voice}"

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        extra: dict[str, Any] = {}
        if sys.platform == "win32":
            extra["creationflags"] = _CREATE_NO_WINDOW
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **extra,
        )
        header = await self._header(self._startup_timeout)
        if not header.get("ready"):
            await self.aclose()
            msg = f"o Kokoro não iniciou: {header.get('error', 'resposta inesperada')}"
            raise TTSError(msg)
        self.voices = list(header.get("voices", []))
        if self.voices and self._voice not in self.voices:
            await self.aclose()
            msg = f"a voz {self._voice} não existe no Kokoro"
            raise TTSError(msg)

    async def synthesize(self, text: str) -> Audio:
        async with self._lock:
            await self.start()
            stdin, stdout = self._pipes()
            request = {"text": text, "voice": self._voice, "speed": self._speed, "lang": self._lang}
            stdin.write(json.dumps(request, ensure_ascii=False).encode() + b"\n")
            await stdin.drain()
            header = await self._header(self._request_timeout)
            if "error" in header:
                msg = f"o Kokoro falhou: {header['error']}"
                raise TTSError(msg)
            payload = await asyncio.wait_for(
                stdout.readexactly(int(header["bytes"])), self._request_timeout
            )
            return Audio.from_pcm16(payload, int(header["rate"]))

    def _pipes(self) -> tuple[asyncio.StreamWriter, asyncio.StreamReader]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            msg = "o processo do Kokoro não está rodando"
            raise TTSError(msg)
        return process.stdin, process.stdout

    async def _header(self, wait_s: float) -> dict[str, Any]:
        _, stdout = self._pipes()
        try:
            line = await asyncio.wait_for(stdout.readline(), wait_s)
        except TimeoutError as exc:
            msg = "o Kokoro não respondeu a tempo"
            raise TTSError(msg) from exc
        if not line:
            msg = "o processo do Kokoro terminou"
            raise TTSError(msg)
        try:
            header: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = "resposta inválida do Kokoro"
            raise TTSError(msg) from exc
        return header

    async def aclose(self) -> None:
        process, self._process = self._process, None
        if process is None or process.returncode is not None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            process.kill()
            await process.wait()


def build_tts(settings: TTSSettings, data_dir: Path) -> tuple[TextToSpeech, str]:
    """Motor configurado e uma linha de estado. Sem Kokoro, cai para a voz do Windows."""
    if settings.engine == "kokoro":
        files = kokoro_files(data_dir, settings.kokoro_model)
        if kokoro_installed() and files.present:
            tts = KokoroProcessTTS(
                model=files.model, voices=files.voices, voice=settings.voice, speed=settings.speed
            )
            return tts, f"voz: Kokoro {settings.voice}"
        missing = "pacote kokoro-onnx" if not kokoro_installed() else "modelos do Kokoro"
        reason = f"sem {missing} (rode 'shiro voice setup')"
    else:
        reason = ""
    if sys.platform == "win32":
        from shiro.infrastructure.voice.windows.sapi import SapiTTS

        sapi = SapiTTS(voice_hint=settings.sapi_voice, speed=settings.speed)
        prefix = f"{reason}; " if reason else ""
        return sapi, f"{prefix}voz: {settings.sapi_voice} (Windows)"
    msg = reason or "a voz do Windows (SAPI) só existe no Windows"
    raise TTSError(msg)
