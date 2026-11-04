"""Runtime de voz: ajudantes e a montagem completa com dublês."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shiro.config.settings import Settings
from shiro.interfaces.voice.runtime import FanOutNotifier, endpoint_for, wake_enabled
from tests.fakes.voice import FakePlayer


class Keyboard:
    async def ask(self, prompt: str, kind: Any) -> bool:
        return False


async def test_voice_app_helpers() -> None:
    settings = Settings()
    assert not wake_enabled(settings)
    assert wake_enabled(Settings.model_validate({"voice": {"activation": "both"}}))
    assert endpoint_for(settings).end_silence_ms == 700
    got: list[str] = []

    class Sink:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        async def notify(self, title: str, message: str) -> None:
            got.append(f"{self.tag}:{message}")

    await FanOutNotifier(Sink("voz"), Sink("bandeja")).notify("Lembrete", "beber água")
    assert got == ["voz:beber água", "bandeja:beber água"]
    assert FakePlayer().played == []


async def test_voice_runtime_composition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from shiro.infrastructure.voice.stt import FasterWhisperSTT
    from shiro.interfaces.voice import runtime as voice_app
    from tests.fakes.voice import FakeTTS, FakeWhisper, segment

    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path))
    built: list[str | None] = []

    async def fake_whisper(settings: Settings, model: str | None = None, **_: Any) -> Any:
        built.append(model)
        return FasterWhisperSTT(
            settings.voice.stt, factory=lambda _s, _src: FakeWhisper([segment("oi")])
        )

    monkeypatch.setattr(voice_app, "whisper_for", fake_whisper)
    monkeypatch.setattr(voice_app, "tts_for", lambda settings, engine=None: (FakeTTS(), "dublê"))
    settings = Settings.model_validate(
        {"voice": {"activation": "both"}, "policy": {"read_only_mode": False}}
    )
    reports: list[tuple[bool, str]] = []
    runtime = await voice_app.build_voice_runtime(settings, keyboard=Keyboard())
    try:
        await runtime.start(lambda ok, text: reports.append((ok, text)), warmup=False)
        texts = [t for _, t in reports]
        assert any(t.startswith("ouvido:") for t in texts)
        assert any("palavra de ativação" in t for t in texts)
        assert built == [None, "base"]  # Whisper principal e o rápido da palavra de ativação
        assert runtime.wake_active
        runtime.pause_wake(True)
        assert not runtime.wake_active
        await runtime.start_wake(lambda ok, text: None)  # já existe: só religa
        assert runtime.wake_active
        assert runtime.session.idle
        assert runtime.app.agent is not None
    finally:
        await runtime.aclose()
