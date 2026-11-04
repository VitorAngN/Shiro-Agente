"""Escolha do microfone e modos de captura, com um sounddevice de mentira."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from shiro.infrastructure.voice import devices
from shiro.infrastructure.voice.devices import (
    AudioDeviceError,
    SoundDeviceMicrophone,
    resolve_device,
    wasapi_settings,
)

MME, WASAPI = "MME", "Windows WASAPI"


class PortAudioError(Exception):
    pass


class FakeStream:
    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeSD:
    """Dois microfones em duas APIs; ``refuse`` lista o que o PortAudio recusa abrir."""

    PortAudioError = PortAudioError

    def __init__(self, refuse: set[tuple[str, int]] | None = None) -> None:
        self.refuse = refuse or set()
        self.opened: list[dict[str, Any]] = []
        self.default = SimpleNamespace(device=(0, -1))
        self._lib = SimpleNamespace(eStreamOptionRaw=1)
        self._devices = [
            # MME corta o nome em 31 letras; o WASAPI mostra o nome inteiro.
            {"name": "Microfone (Headset Gamer Sem Fio", "hostapi": 0, "rate": 44100, "ch": 2},
            {"name": "Microfone (Realtek Audio)", "hostapi": 0, "rate": 44100, "ch": 2},
            {
                "name": "Microfone (Headset Gamer Sem Fio Wireless Surround)",
                "hostapi": 1,
                "rate": 48000,
                "ch": 2,
            },
            {"name": "Microfone (Realtek Audio)", "hostapi": 1, "rate": 48000, "ch": 2},
        ]

    def query_hostapis(self) -> list[dict[str, Any]]:
        return [
            {"name": MME, "default_input_device": 0, "default_output_device": -1},
            {"name": WASAPI, "default_input_device": 2, "default_output_device": -1},
        ]

    def query_devices(self, device: int | None = None, kind: str | None = None) -> Any:
        rows = [
            {
                "name": d["name"],
                "hostapi": d["hostapi"],
                "max_input_channels": d["ch"],
                "max_output_channels": 0,
                "default_samplerate": float(d["rate"]),
            }
            for d in self._devices
        ]
        if device is None:  # com ``kind``, o sounddevice devolve o aparelho padrão
            return rows if kind is None else rows[self.default.device[0]]
        return rows[device]

    class WasapiSettings:
        def __init__(self, exclusive: bool = False) -> None:
            self.exclusive = exclusive
            self._streaminfo = SimpleNamespace(streamOption=0)

    def InputStream(self, **kwargs: Any) -> FakeStream:  # noqa: N802 - mesmo nome do sounddevice
        key = ("wasapi" if "extra_settings" in kwargs else "mme", kwargs["channels"])
        refuses_16k = ("mme16k", 0) in self.refuse and kwargs["samplerate"] == 16000
        if key in self.refuse or refuses_16k:
            raise PortAudioError(str(key))
        self.opened.append(kwargs)
        return FakeStream()


@pytest.fixture
def sd(monkeypatch: pytest.MonkeyPatch) -> FakeSD:
    fake = FakeSD()
    monkeypatch.setattr(devices, "_sd", lambda: fake)
    return fake


def test_by_name_prefers_mme_unless_a_host_api_is_asked(sd: FakeSD) -> None:
    assert resolve_device("headset", kind="input") == 0
    assert resolve_device("headset", kind="input", hostapi=WASAPI) == 2
    assert resolve_device("default", kind="input") is None  # padrão do Windows
    assert resolve_device("default", kind="input", hostapi=WASAPI) == 2
    with pytest.raises(AudioDeviceError, match="no Windows WASAPI"):
        resolve_device("blue yeti", kind="input", hostapi=WASAPI)
    with pytest.raises(AudioDeviceError, match="saída"):
        resolve_device("default", kind="output", hostapi=WASAPI)


def test_raw_and_exclusive_settings(sd: FakeSD) -> None:
    raw = wasapi_settings(sd, "raw")
    assert raw._streaminfo.streamOption == 1 and not raw.exclusive  # som cru, compartilhado
    assert wasapi_settings(sd, "exclusive").exclusive
    assert wasapi_settings(sd, "wasapi")._streaminfo.streamOption == 0
    sd._lib = SimpleNamespace()  # sounddevice antigo, sem a opção
    with pytest.raises(AudioDeviceError, match="raw"):
        wasapi_settings(sd, "raw")


async def test_wasapi_opens_at_the_device_rate_and_retries_with_its_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSD(refuse={("wasapi", 1)})  # exclusivo: só aceita o formato do aparelho
    monkeypatch.setattr(devices, "_sd", lambda: fake)
    async with SoundDeviceMicrophone("headset", "exclusive").open():
        pass
    opened = fake.opened[-1]
    assert (opened["device"], opened["samplerate"], opened["channels"]) == (2, 48000, 2)
    assert opened["blocksize"] == 1536  # 32 ms a 48 kHz
    assert opened["extra_settings"].exclusive


async def test_a_mode_that_does_not_open_falls_back_to_mme_only_when_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSD(refuse={("wasapi", 1), ("wasapi", 2)})
    monkeypatch.setattr(devices, "_sd", lambda: fake)
    async with SoundDeviceMicrophone("headset", "raw").open():
        pass
    assert "extra_settings" not in fake.opened[-1]  # voltou ao MME
    assert fake.opened[-1]["device"] == 0
    with pytest.raises(AudioDeviceError, match="raw"):
        async with SoundDeviceMicrophone("headset", "raw", fallback=False).open():
            pass


async def test_mme_converts_when_the_device_refuses_16_khz(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSD(refuse={("mme16k", 0)})
    monkeypatch.setattr(devices, "_sd", lambda: fake)
    async with SoundDeviceMicrophone().open():
        pass
    assert fake.opened[-1]["samplerate"] == 44100 and fake.opened[-1]["device"] is None
