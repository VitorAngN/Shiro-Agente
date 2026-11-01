"""Fase 2 (sempre ligado): palavra de ativação, janela de continuação, bandeja e sistema."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from shiro import autostart
from shiro.activities.service import ActivityService
from shiro.interfaces.tray import LogStream, MenuEntry, TrayController, menu_entries
from shiro.interfaces.tray_icons import COLORS, PAUSED, icon_image, tooltip
from shiro.interfaces.voice import Phase, Trigger, TriggerSource
from shiro.persistence.activities import SqliteActivityStore, SqliteJobStore
from shiro.persistence.database import Database
from shiro.settings import Settings
from shiro.singleton import AlreadyRunningError, single_instance
from shiro.tray_main import RuntimeActions, day_summary
from shiro.voice import models
from shiro.voice.audio import Audio
from shiro.voice.ports import Transcript
from shiro.voice.vad import EndpointConfig
from shiro.voice.wake import WakeListener, strip_wake, wake_match
from shiro.voice_app import FanOutNotifier, endpoint_for, wake_enabled
from tests.fakes import SAO_PAULO
from tests.unit.test_voice import FakeMic, ScriptedDetector, frames
from tests.unit.test_voice_session import FakePlayer, make_session, until

PHRASES = ("ei shiro", "oi shiro", "ok shiro", "hey shiro", "shiro")

# ---------------------------------------------------------------------- "Ei, Shiro"


@pytest.mark.parametrize(
    ("heard", "rest"),
    [
        ("Ei, Shiro!", ""),
        ("Shiro.", ""),
        ("Ei Xiro, abre o Spotify.", "abre o spotify"),
        ("Oi, Chiro, que horas são?", "que horas sao"),
        ("Hum, ei Shiro, pausa a música", "pausa a musica"),
        ("Ok Shiro", ""),
        # como o Whisper escreve o chamado (medido no PC de referência)
        ("Aiciro.", ""),
        ("Aishiro, abre o Spotify.", "abre o spotify"),
        ("Eishiro, abre o Spotify.", "abre o spotify"),
        ("A. Shiro.", ""),
        ("E Shiro, abre o Spotify.", "abre o spotify"),
        ("A Shiro é legal", None),  # artigo sem vírgula: falando dela, não com ela
        ("Ciro, me passa o sal", None),
        ("O Shiro é legal", None),  # o nome no meio de uma conversa não ativa
        ("Eu falei com a Shiro ontem", None),
        ("Abre o Spotify", None),
        ("", None),
    ],
)
def test_wake_match(heard: str, rest: str | None) -> None:
    assert wake_match(heard, PHRASES) == rest


def test_strip_wake_keeps_accents_of_the_request() -> None:
    assert strip_wake("Ei, Shiro, que horas são?", PHRASES) == "que horas são?"
    assert strip_wake("Shiro abre o VS Code", PHRASES) == "abre o VS Code"
    assert strip_wake("abre o Spotify", PHRASES) == "abre o Spotify"
    assert strip_wake("E Shiro, abre o Spotify.", PHRASES) == "abre o Spotify."
    assert strip_wake("Aishiro, pausa a música", PHRASES) == "pausa a música"
    assert wake_match("Ei Kira, abre o Spotify", ("ei kira",)) == "abre o spotify"


class Events:
    def __init__(self) -> None:
        self.got: list[str] = []

    def wake(self) -> None:
        self.got.append("wake")

    def command(self, text: str) -> None:
        self.got.append(f"command:{text}")


class SequenceSTT:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.calls = 0

    async def load(self) -> None:
        return None

    async def transcribe(self, audio: Audio) -> Transcript:
        self.calls += 1
        return Transcript(self.texts.pop(0) if self.texts else "", audio.duration, 1)


def utterance(speech_frames: int = 10) -> list[np.ndarray]:
    return frames(3) + frames(speech_frames, 0.9) + frames(25)


async def test_whisper_wake_listener() -> None:
    blocks = utterance() + utterance() + utterance() + utterance(300)
    check = SequenceSTT(["Ei, Shiro", "conversa qualquer", "Ei Shiro, abre o Spotify"])
    full = SequenceSTT(["Ei Shiro, abre o Spotify."])
    events = Events()
    listener = WakeListener(
        microphone=FakeMic(blocks), events=events, is_idle=lambda: True, cooldown_s=0
    )

    await listener.run_whisper(
        vad=ScriptedDetector(),
        check=check,
        full=full,
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320, max_utterance_s=15),
        max_phrase_s=3.0,
    )

    assert events.got == ["wake", "command:abre o Spotify."]
    assert check.calls == 3  # a fala longa (9,6 s > 3 s) nem foi transcrita
    assert full.calls == 1


async def test_wake_is_ignored_while_busy_or_disabled() -> None:
    events = Events()
    busy = WakeListener(microphone=FakeMic(utterance()), events=events, is_idle=lambda: False)
    await busy.run_whisper(
        vad=ScriptedDetector(),
        check=SequenceSTT(["Ei Shiro"]),
        full=SequenceSTT([]),
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320),
        max_phrase_s=8,
    )
    off = WakeListener(microphone=FakeMic(utterance()), events=events, is_idle=lambda: True)
    off.enabled = False
    await off.run_whisper(
        vad=ScriptedDetector(),
        check=SequenceSTT(["Ei Shiro"]),
        full=SequenceSTT([]),
        phrases=PHRASES,
        listen=EndpointConfig(end_silence_ms=320),
        max_phrase_s=8,
    )
    assert events.got == []


class ScriptedWakeModel:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.resets = 0

    def score(self, chunk: np.ndarray) -> float:
        assert chunk.dtype == np.int16 and chunk.shape == (1280,)
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self) -> None:
        self.resets += 1


async def test_openwakeword_listener_fires_once_per_cooldown() -> None:
    model = ScriptedWakeModel([0.1, 0.9, 0.95, 0.2, 0.1])
    events = Events()
    blocks = frames(13)  # 13 x 512 = 6656 amostras = 5 blocos de 1280
    listener = WakeListener(microphone=FakeMic(blocks), events=events, is_idle=lambda: True)
    await listener.run_openwakeword(model, threshold=0.5)  # type: ignore[arg-type]
    assert events.got == ["wake"]  # o segundo pico cai no tempo de espera
    assert model.resets == 1


async def test_openwakeword_files_are_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"onnx"
    for name in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        monkeypatch.setitem(models.KNOWN_SHA256, name, hashlib.sha256(body).hexdigest())
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    files = await models.ensure_openwakeword(client, tmp_path, "hey_jarvis")
    assert files.wakeword.name == "hey_jarvis_v0.1.onnx" and files.melspectrogram.is_file()

    custom = tmp_path / "ei_shiro.onnx"
    custom.write_bytes(b"x")
    assert (await models.ensure_openwakeword(client, tmp_path, str(custom))).wakeword == custom
    with pytest.raises(models.DownloadError, match="não encontrado"):
        await models.ensure_openwakeword(client, tmp_path, str(tmp_path / "nada.onnx"))
    await client.aclose()


# ---------------------------------------------------------------------- sessão


async def test_spoken_command_and_follow_up_window() -> None:
    phases: list[Phase] = []
    session, _, tts, _, asked, _ = make_session(
        heard=["e amanhã?"], mic_blocks=utterance() + utterance()
    )
    session._follow_up_s = 2.0  # pyright: ignore[reportPrivateUsage]
    session._on_phase = phases.append  # pyright: ignore[reportPrivateUsage]

    await session.interaction("como tá o tempo hoje", spoken=True)

    # pedido falado com "Ei, Shiro", depois um de continuação, sem chamar de novo
    assert asked == ["como tá o tempo hoje", "e amanhã?"]
    assert Phase.THINKING in phases and Phase.LISTENING in phases
    assert session.phase is Phase.IDLE and session.idle
    assert len(tts.spoken) == 2


async def test_follow_up_window_closes_quietly() -> None:
    session, _, _, _, asked, out = make_session(heard=[], mic_blocks=frames(100))
    session._follow_up_s = 0.5  # pyright: ignore[reportPrivateUsage]
    await session.interaction("que horas são", spoken=False)
    assert asked == ["que horas são"]
    assert "não ouvi nada" not in out.getvalue()  # sem bipe de erro no fim da janela


async def test_run_loop_accepts_spoken_triggers() -> None:
    session, _, _, _, asked, _ = make_session(heard=[])
    triggers = TriggerSource()
    triggers.command("pula essa música")
    runner = asyncio.create_task(session.run(triggers))
    await until(lambda: bool(asked))
    await until(lambda: session.idle)
    triggers.wake()
    triggers.put(Trigger("quit"))
    await asyncio.wait_for(runner, 2)
    assert asked == ["pula essa música"]


# ---------------------------------------------------------------------- bandeja


def test_icons_follow_the_palette() -> None:
    for phase, color in COLORS.items():
        image = icon_image(phase, size=64)
        assert image.size == (64, 64)
        assert image.getpixel((32, 32)) == color  # o visor no centro
    assert icon_image(Phase.IDLE, paused=True).getpixel((32, 32)) == PAUSED
    assert icon_image(Phase.LISTENING, paused=True).getpixel((32, 32)) == COLORS[Phase.LISTENING]
    assert tooltip("Shiro", Phase.THINKING) == "Shiro: pensando"
    assert tooltip("Shiro", Phase.IDLE, paused=True) == "Shiro: escuta pausada"


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.wake = False

    def talk(self) -> None:
        self.calls.append("talk")

    def stop(self) -> None:
        self.calls.append("stop")

    async def toggle_wake(self) -> None:
        self.wake = not self.wake
        self.calls.append("wake")

    def wake_active(self) -> bool:
        return self.wake

    async def release_gpu(self) -> None:
        self.calls.append("gpu")

    async def toggle_autostart(self) -> None:
        self.calls.append("autostart")

    def autostart_enabled(self) -> bool:
        return False

    def open_logs(self) -> None:
        self.calls.append("logs")

    def quit(self) -> None:
        self.calls.append("quit")


async def test_tray_menu_runs_actions_on_the_event_loop() -> None:
    actions = FakeActions()
    entries = menu_entries(actions)
    labels = [e.label if e else "---" for e in entries]
    assert labels[0] == "Falar agora" and labels[-1] == "Sair"
    assert [e.label for e in entries if e and e.default] == ["Falar agora"]
    tray = TrayController(name="Shiro", loop=asyncio.get_running_loop())

    def press(label: str) -> None:
        entry = next(e for e in entries if e and e.label.startswith(label))
        # O pystray chama de outra thread; o controlador leva para o laço do asyncio.
        asyncio.get_running_loop().run_in_executor(None, tray.dispatch, entry)

    press("Falar")
    press("Ouvir")
    press("Liberar")
    await until(lambda: len(actions.calls) == 3)
    wake = next(e for e in entries if isinstance(e, MenuEntry) and e.checked is not None)
    assert wake.checked is not None and wake.checked()
    assert sorted(actions.calls) == ["gpu", "talk", "wake"]
    tray.set_phase(Phase.SPEAKING)  # sem ícone criado: não faz nada
    await tray.notify("t", "m")
    tray.stop()


def test_log_stream(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="shiro.interfaces.tray"):
        print("shiro ▸ Volume em 20%.\n\n", file=LogStream())
    assert "voz: shiro ▸ Volume em 20%." in caplog.text


class FakeRuntime:
    def __init__(self) -> None:
        self.triggers = TriggerSource()
        self.wake: Any = None
        self.started: list[str] = []
        self.app = type("A", (), {"local_llm": object()})()

    @property
    def wake_active(self) -> bool:
        return self.wake is not None and self.wake.enabled

    async def start_wake(self, report: Callable[[bool, str], None]) -> None:
        self.wake = type("W", (), {"enabled": True})()
        report(True, "ok")

    def pause_wake(self, paused: bool) -> None:
        self.wake.enabled = not paused


async def test_runtime_actions() -> None:
    runtime = FakeRuntime()
    tray = TrayController(name="Shiro", loop=asyncio.get_running_loop())
    actions = RuntimeActions(runtime, tray)  # type: ignore[arg-type]
    actions.talk()
    actions.stop()
    actions.quit()
    got = [await runtime.triggers.next() for _ in range(3)]
    assert [t.kind for t in got] == ["talk", "stop", "quit"]

    await actions.toggle_wake()  # liga pela primeira vez
    assert actions.wake_active() and not tray.paused
    await actions.toggle_wake()  # pausa
    assert not actions.wake_active() and tray.paused
    await actions.release_gpu()  # modelo sem "release": nada a fazer


async def test_day_summary() -> None:
    from tests.unit.test_activities import MovableClock

    database = await Database.open(":memory:")
    clock = MovableClock(datetime(2026, 11, 4, 8, 0, tzinfo=SAO_PAULO))
    service = ActivityService(
        store=SqliteActivityStore(database), jobs=SqliteJobStore(database), clock=clock
    )
    assert await day_summary(service) == "Nada para hoje."
    await service.create("prova de física", "hoje às 19h", None)
    summary = await day_summary(service)
    assert "prova de física" in summary
    await database.close()


# ---------------------------------------------------------------------- sistema


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o mutex é do sistema")
def test_single_instance(tmp_path: Path) -> None:
    first = single_instance("teste", lock_dir=tmp_path)
    with pytest.raises(AlreadyRunningError):
        single_instance("teste", lock_dir=tmp_path)
    first.release()
    first.release()  # liberar duas vezes não quebra
    single_instance("teste", lock_dir=tmp_path).release()


def test_autostart_task_xml_and_launcher(tmp_path: Path) -> None:
    scripts = tmp_path / "proj" / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    python = scripts / "python.exe"
    python.write_text("")
    fallback = autostart.launcher(python)
    assert fallback.arguments == "-m shiro.tray_main"
    tray = scripts / ("shiro-tray.exe" if sys.platform == "win32" else "shiro-tray")
    tray.write_text("")
    target = autostart.launcher(python)
    assert target.command == str(tray) and target.arguments == ""
    assert target.working_dir == str(tmp_path / "proj")

    xml = autostart.task_xml(
        autostart.Launcher("C:\\A & B\\shiro-tray.exe", "", "C:\\proj"), "PC\\eu", delay_s=45
    )
    assert "<Delay>PT45S</Delay>" in xml
    assert "C:\\A &amp; B\\shiro-tray.exe" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    if sys.platform != "win32":
        assert autostart.status() is None
        assert not autostart.disable()
        with pytest.raises(autostart.AutostartError):
            autostart.enable()


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


class FakeOnnx:
    """Sessão ONNX de mentira que confere os formatos que o openWakeWord espera."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls = 0

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "x", "shape": [1, 16, 96]})()]

    def run(self, _: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.calls += 1
        (value,) = feed.values()
        if self.kind == "mel":
            assert value.ndim == 2 and value.dtype == np.float32
            frames_out = max(1, (value.shape[1] - 400) // 160)
            return [np.zeros((1, 1, frames_out, 32), dtype=np.float32)]
        if self.kind == "embedding":
            assert value.shape[1:] == (76, 32, 1)
            return [np.ones((value.shape[0], 1, 1, 96), dtype=np.float32)]
        assert value.shape == (1, 16, 96)
        return [np.array([[0.75]], dtype=np.float32)]


def test_openwakeword_pipeline_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    from shiro.voice import oww

    kinds = iter(["mel", "embedding", "wake"])
    monkeypatch.setattr(oww, "_session", lambda path: FakeOnnx(next(kinds)))
    detector = oww.OpenWakeWord(melspectrogram=Path("m"), embedding=Path("e"), wakeword=Path("w"))
    chunk = np.zeros(oww.CHUNK, dtype=np.int16)
    scores = [detector.score(chunk) for _ in range(7)]
    assert scores[:5] == [0.0] * 5  # aquecimento, como no openWakeWord
    assert scores[5:] == [0.75, 0.75]
    with pytest.raises(ValueError, match="1280"):
        detector.score(np.zeros(100, dtype=np.int16))


async def test_voice_runtime_composition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from shiro import voice_app
    from shiro.voice.stt import FasterWhisperSTT
    from tests.unit.test_voice import FakeWhisper, segment
    from tests.unit.test_voice_session import FakeTTS

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


class Keyboard:
    async def ask(self, prompt: str, kind: Any) -> bool:
        return False
