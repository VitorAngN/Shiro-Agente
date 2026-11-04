"""Microfone e alto-falante com sounddevice (PortAudio).

``sounddevice`` é importado só quando o áudio é usado: no Linux do CI não há
PortAudio instalado, e os testes usam dublês destas classes.

No Windows o mesmo aparelho aparece uma vez por API de áudio (MME, DirectSound,
WASAPI...). Ao escolher pelo nome, a preferência é o MME, que aceita qualquer
taxa de amostragem e converte sozinho.

O MME passa pelos efeitos de áudio do Windows (APOs: supressão de ruído, "voice
clarity", o que o fabricante instalou), e alguns deles cortam o começo da fala.
Os modos WASAPI ``raw`` e ``exclusive`` pedem o som sem esses efeitos;
``shiro voice mic-test`` compara os modos no seu microfone (ADR-0021).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from shiro.domain.voice.audio import STT_RATE, Audio, Samples
from shiro.domain.voice.endpointing import FRAME

log = logging.getLogger(__name__)

_WASAPI = "Windows WASAPI"
_HOSTAPI_PREFERENCE = ("MME", "Windows DirectSound", _WASAPI)
_QUEUE_FRAMES = 300  # ~10 s de folga se o laço de eventos atrasar

type Capture = Literal["mme", "wasapi", "raw", "exclusive"]
CAPTURE_MODES: tuple[Capture, ...] = ("mme", "wasapi", "raw", "exclusive")
"""Como pedir o som ao Windows.

* ``mme``: o jeito de sempre; o Windows converte a taxa e aplica os efeitos;
* ``wasapi``: o mesmo caminho pelo WASAPI compartilhado (serve de comparação);
* ``raw``: WASAPI compartilhado pedindo o som cru, sem os efeitos (se o aparelho deixar);
* ``exclusive``: WASAPI exclusivo, direto do aparelho; nenhum outro app usa o microfone
  enquanto a SHIRO ouve.
"""


class AudioDeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    inputs: int
    outputs: int
    default_rate: int
    is_default_input: bool
    is_default_output: bool


def _sd() -> Any:
    try:
        import sounddevice
    except OSError as exc:  # PortAudio ausente (Linux sem libportaudio2)
        msg = f"áudio indisponível: {exc}"
        raise AudioDeviceError(msg) from exc
    return sounddevice


def list_devices() -> list[DeviceInfo]:
    sd = _sd()
    hostapis = [h["name"] for h in sd.query_hostapis()]
    default_in, default_out = sd.default.device
    return [
        DeviceInfo(
            index=i,
            name=d["name"],
            hostapi=hostapis[d["hostapi"]],
            inputs=d["max_input_channels"],
            outputs=d["max_output_channels"],
            default_rate=int(d["default_samplerate"]),
            is_default_input=i == default_in,
            is_default_output=i == default_out,
        )
        for i, d in enumerate(sd.query_devices())
    ]


def resolve_device(name: str, *, kind: str, hostapi: str | None = None) -> int | None:
    """Índice do aparelho cujo nome contém ``name``; ``None`` para o padrão do Windows.

    Com ``hostapi``, procura só naquela API (e o padrão vira o padrão dela).
    """
    label = "entrada" if kind == "input" else "saída"
    if not name or name.casefold() == "default":
        return None if hostapi is None else _hostapi_default(hostapi, kind)
    wanted = name.casefold()
    found = [
        d
        for d in list_devices()
        if wanted in d.name.casefold()
        and (d.inputs if kind == "input" else d.outputs) > 0
        and hostapi in (None, d.hostapi)
    ]
    if not found:
        where = f" no {hostapi}" if hostapi else ""
        msg = f'nenhum aparelho de {label} com "{name}"{where}'
        raise AudioDeviceError(msg)

    def rank(device: DeviceInfo) -> int:
        try:
            return _HOSTAPI_PREFERENCE.index(device.hostapi)
        except ValueError:
            return len(_HOSTAPI_PREFERENCE)

    return min(found, key=rank).index


def _hostapi_default(hostapi: str, kind: str) -> int:
    key = "default_input_device" if kind == "input" else "default_output_device"
    for info in _sd().query_hostapis():
        if info["name"] == hostapi:
            index = int(info[key])
            if index >= 0:
                return index
    msg = f"o {hostapi} não tem aparelho padrão de {'entrada' if kind == 'input' else 'saída'}"
    raise AudioDeviceError(msg)


def wasapi_settings(sd: Any, capture: Capture) -> Any:
    """Opções do WASAPI para o modo; ``raw`` mexe num campo que o sounddevice não expõe."""
    settings = sd.WasapiSettings(exclusive=capture == "exclusive")
    if capture == "raw":
        info = getattr(settings, "_streaminfo", None)
        lib = getattr(sd, "_lib", None)
        if info is None or lib is None or not hasattr(lib, "eStreamOptionRaw"):
            msg = "esta versão do sounddevice não deixa pedir o som cru (modo raw)"
            raise AudioDeviceError(msg)
        info.streamOption = lib.eStreamOptionRaw
    return settings


class SoundDeviceMicrophone:
    """Quadros de 512 amostras a 16 kHz. Se o aparelho não aceitar 16 kHz, converte.

    Se o modo de captura configurado não abrir, volta para o MME e avisa no log:
    a voz continua funcionando.
    """

    def __init__(
        self, device: str = "default", capture: Capture = "mme", *, fallback: bool = True
    ) -> None:
        """``fallback=False``: falha em vez de voltar ao MME (para comparar os modos)."""
        self._device = device
        self._capture: Capture = capture
        self._fallback = fallback

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
        sd = _sd()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Samples] = asyncio.Queue(maxsize=_QUEUE_FRAMES)

        def put(block: Samples) -> None:
            if queue.full():
                queue.get_nowait()  # descarta o mais antigo; nunca bloqueia o PortAudio
            queue.put_nowait(block)

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            loop.call_soon_threadsafe(put, indata[:, 0].astype(np.float32).copy())

        if self._capture == "mme":
            stream, rate = _mme_stream(sd, self._device, callback)
        else:
            try:
                stream, rate = _wasapi_stream(sd, self._device, self._capture, callback)
            except AudioDeviceError as exc:
                if not self._fallback:
                    raise
                log.warning("captura %s indisponível (%s); usando o MME", self._capture, exc)
                stream, rate = _mme_stream(sd, self._device, callback)
        with stream:
            yield _frames(queue, rate)


def _mme_stream(sd: Any, name: str, callback: Any) -> tuple[Any, int]:
    device = resolve_device(name, kind="input")
    try:
        stream = sd.InputStream(
            samplerate=STT_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME,
            device=device,
            callback=callback,
        )
        return stream, STT_RATE
    except sd.PortAudioError:
        rate = int(sd.query_devices(device, "input")["default_samplerate"])
        stream = sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            blocksize=round(FRAME * rate / STT_RATE),
            device=device,
            callback=callback,
        )
        return stream, rate


def _wasapi_stream(sd: Any, name: str, capture: Capture, callback: Any) -> tuple[Any, int]:
    """WASAPI na taxa do próprio aparelho (a conversão para 16 kHz é nossa)."""
    device = resolve_device(name, kind="input", hostapi=_WASAPI)
    info = sd.query_devices(device, "input")
    rate = int(info["default_samplerate"])
    extra = wasapi_settings(sd, capture)
    failure: Exception | None = None
    # O modo exclusivo exige o formato do aparelho: tenta mono e depois os canais dele.
    for channels in dict.fromkeys((1, int(info["max_input_channels"]))):
        try:
            stream = sd.InputStream(
                samplerate=rate,
                channels=channels,
                dtype="float32",
                blocksize=round(FRAME * rate / STT_RATE),
                device=device,
                callback=callback,
                extra_settings=extra,
            )
            return stream, rate
        except sd.PortAudioError as exc:
            failure = exc
    msg = f"o modo {capture} não abriu o microfone: {failure}"
    raise AudioDeviceError(msg)


async def _frames(queue: asyncio.Queue[Samples], rate: int) -> AsyncIterator[Samples]:
    """Converte para 16 kHz e reagrupa em quadros de exatamente 512 amostras."""
    pending = np.zeros(0, dtype=np.float32)
    while True:
        block = await queue.get()
        if rate != STT_RATE:
            block = Audio(block, rate).resampled(STT_RATE).samples
        pending = np.concatenate([pending, block])
        while len(pending) >= FRAME:
            yield pending[:FRAME]
            pending = pending[FRAME:]


class SoundDevicePlayer:
    """Toca áudio e pode ser interrompido a qualquer momento por ``stop``."""

    def __init__(self, device: str = "default") -> None:
        self._device = device
        self._stopped = threading.Event()

    def stop(self) -> None:
        self._stopped.set()

    async def play(self, audio: Audio) -> bool:
        if len(audio.samples) == 0:
            return True
        self._stopped.clear()
        return await asyncio.to_thread(self._play_blocking, audio)

    def _play_blocking(self, audio: Audio) -> bool:
        sd = _sd()
        device = resolve_device(self._device, kind="output")
        try:
            return self._stream(sd, audio, device)
        except sd.PortAudioError:
            rate = int(sd.query_devices(device, "output")["default_samplerate"])
            return self._stream(sd, audio.resampled(rate), device)

    def _stream(self, sd: Any, audio: Audio, device: int | None) -> bool:
        finished = threading.Event()
        position = 0
        samples = audio.samples

        def callback(outdata: Any, frames: int, time_info: Any, status: Any) -> None:
            nonlocal position
            if self._stopped.is_set():
                raise sd.CallbackStop
            chunk = samples[position : position + frames]
            outdata[: len(chunk), 0] = chunk
            outdata[len(chunk) :, 0] = 0
            position += frames
            if len(chunk) < frames:
                raise sd.CallbackStop

        with sd.OutputStream(
            samplerate=audio.rate,
            channels=1,
            dtype="float32",
            device=device,
            callback=callback,
            finished_callback=finished.set,
        ):
            while not finished.wait(0.05):
                if self._stopped.is_set():
                    break
        return not self._stopped.is_set()
