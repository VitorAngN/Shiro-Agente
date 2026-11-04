"""Composição da voz: monta a SHIRO falante para o terminal (``shiro voice``) e a bandeja.

Junta o ``App`` (agente, ferramentas, agendador) com Whisper, voz, microfone,
atalhos globais e a palavra de ativação. Como ``app.py``, é a única camada que
conhece todas as peças.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TextIO

from shiro.bootstrap.app import App, build_app
from shiro.config import paths
from shiro.config.settings import Settings
from shiro.domain.ports import ConfirmationChannel, LLMError, Notifier
from shiro.domain.voice.audio import Cues
from shiro.domain.voice.endpointing import EndpointConfig
from shiro.domain.voice.ports import TextToSpeech
from shiro.infrastructure.voice.stt import (
    FasterWhisperSTT,
    vocabulary_hotwords,
    vocabulary_prompt,
)
from shiro.interfaces.text.theme import Theme
from shiro.interfaces.voice.session import (
    Phase,
    TriggerSource,
    VoiceConfirmation,
    VoiceNotifier,
    VoiceSession,
)

log = logging.getLogger(__name__)

type Report = Callable[[bool, str], None]

_last_step: dict[str, int] = {}


def print_progress(name: str, done: int, total: int | None) -> None:
    """Progresso de download no terminal (uma linha a cada 25% se a saída for redirecionada)."""
    if sys.stdout is None:  # janela sem console (bandeja)
        return
    if not sys.stdout.isatty():
        if total and (step := 100 * done // total // 25) != _last_step.get(name):
            _last_step[name] = step
            print(f"  {name}: {25 * step}%", flush=True)  # noqa: T201
        return
    share = f"{100 * done / total:5.1f}%" if total else f"{done / 2**20:.0f} MB"
    print(f"\r  {name}: {share}", end="", flush=True)  # noqa: T201


def tts_for(settings: Settings, engine: str | None = None) -> tuple[TextToSpeech, str]:
    from shiro.infrastructure.voice.tts import build_tts

    tts_settings = settings.voice.tts
    if engine is not None:
        tts_settings = tts_settings.model_copy(update={"engine": engine})
    return build_tts(tts_settings, paths.data_dir())


def app_labels(settings: Settings) -> list[str]:
    return [entry.label for entry in settings.policy.allowed_apps.values()]


async def whisper_for(
    settings: Settings,
    model: str | None = None,
    *,
    threads: int | None = None,
    hotwords: bool | None = None,
    device: str | None = None,
) -> FasterWhisperSTT:
    """Whisper com o modelo baixado pelo SHIRO (com verificação de hash), ainda não carregado."""
    import httpx

    from shiro.infrastructure.voice.models import ensure_whisper, whisper_ready

    update: dict[str, object] = {}
    if model is not None:
        update["model"] = model
    if threads is not None:
        update["threads"] = threads
    if hotwords is not None:
        update["hotwords"] = hotwords
    if device is not None:
        update.update(device=device, compute_type="int8_float16" if device == "cuda" else "int8")
    stt_settings = settings.voice.stt.model_copy(update=update)
    data_dir = paths.data_dir()
    ready = whisper_ready(data_dir, stt_settings.model)
    if not ready and sys.stdout is not None:
        print(f"baixando o Whisper {stt_settings.model} (só na primeira vez)…")  # noqa: T201
    timeout = httpx.Timeout(30.0, read=60.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        folder = await ensure_whisper(
            client, data_dir, stt_settings.model, None if ready else print_progress
        )
    if not ready and sys.stdout is not None:
        print()  # noqa: T201
    name, apps = settings.general.assistant_name, app_labels(settings)
    prompt = vocabulary_prompt(name, apps)
    words = vocabulary_hotwords(name, apps) if stt_settings.hotwords else ""
    return FasterWhisperSTT(stt_settings, source=str(folder), prompt=prompt, hotwords=words)


def endpoint_for(settings: Settings) -> EndpointConfig:
    listen = settings.voice.listen
    return EndpointConfig(
        threshold=listen.threshold,
        start_timeout_s=listen.start_timeout_s,
        end_silence_ms=listen.end_silence_ms,
        max_utterance_s=listen.max_utterance_s,
        pre_roll_ms=listen.pre_roll_ms,
    )


def wake_enabled(settings: Settings) -> bool:
    return settings.voice.activation in ("wake_word", "both")


class FanOutNotifier:
    """Entrega o mesmo aviso para várias saídas (voz e notificação da bandeja)."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    async def notify(self, title: str, message: str) -> None:
        for notifier in self._notifiers:
            await notifier.notify(title, message)


@dataclass
class VoiceRuntime:
    settings: Settings
    app: App
    session: VoiceSession
    triggers: TriggerSource
    tts: TextToSpeech
    stt: FasterWhisperSTT
    talk_hint: str = "Enter"
    hotkeys: Any = None
    wake: Any = None
    _wake_task: asyncio.Task[None] | None = None
    _closers: list[Callable[[], Awaitable[None]]] = field(
        default_factory=list[Callable[[], Awaitable[None]]]
    )

    async def start(self, report: Report, *, warmup: bool = True) -> None:
        """Carrega modelos, liga atalhos e palavra de ativação, e o agendador."""
        settings = self.settings
        if warmup:
            try:
                await self.app.agent.warm_up()
                report(True, f"{settings.llm.local.model} carregado")
            except LLMError as exc:
                report(False, f"modelo local offline ({exc}); comandos simples continuam")
        await self.stt.load()
        report(True, f"ouvido: {self.stt.name}")
        start = getattr(self.tts, "start", None)
        if start is not None:
            await start()
        report(True, f"voz: {self.tts.name}")
        self._start_hotkeys(report)
        if wake_enabled(settings):
            await self.start_wake(report)
        self.app.start_background()

    def _start_hotkeys(self, report: Report) -> None:
        if sys.platform != "win32":
            return
        from shiro.domain.voice.hotkeys import HotkeyError
        from shiro.infrastructure.voice.windows.hotkeys import WindowsHotkeys

        voice = self.settings.voice
        try:
            self.hotkeys = WindowsHotkeys(
                {"talk": voice.push_to_talk_hotkey, "stop": voice.stop_hotkey}
            )
            self.hotkeys.start()
        except HotkeyError as exc:
            self.hotkeys = None
            report(False, str(exc))
            return
        self.triggers.add(self.hotkeys.next)
        self.talk_hint = voice.push_to_talk_hotkey
        report(True, f"atalhos: falar {voice.push_to_talk_hotkey}, parar {voice.stop_hotkey}")

    async def start_wake(self, report: Report) -> None:
        """Liga a escuta de "Ei, Shiro" (também pela bandeja, em tempo de execução)."""
        import httpx

        from shiro.infrastructure.voice.devices import SoundDeviceMicrophone
        from shiro.infrastructure.voice.models import ensure_openwakeword
        from shiro.infrastructure.voice.oww import OpenWakeWord
        from shiro.infrastructure.voice.silero import SileroVAD
        from shiro.infrastructure.voice.wake import WakeListener

        if self._wake_task is not None and not self._wake_task.done():
            self.wake.enabled = True
            return
        voice = self.settings.voice
        word = voice.wake_word
        listener = WakeListener(
            microphone=SoundDeviceMicrophone(voice.input_device),
            events=self.triggers,
            is_idle=lambda: self.session.idle,
        )
        work: Callable[[], Awaitable[None]]
        if word.engine == "openwakeword":
            model = word.model_path or word.model
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                files = await ensure_openwakeword(client, paths.data_dir(), model)
            detector = OpenWakeWord(
                melspectrogram=files.melspectrogram,
                embedding=files.embedding,
                wakeword=files.wakeword,
            )

            def work() -> Awaitable[None]:
                return listener.run_openwakeword(detector, word.threshold)

            label = f"palavra de ativação: openWakeWord ({model})"
        else:
            check = await whisper_for(self.settings, word.check_model, threads=2)
            await check.load()
            endpoint = endpoint_for(self.settings)

            def work() -> Awaitable[None]:
                return listener.run_whisper(
                    vad=SileroVAD(),
                    check=check,
                    full=self.stt,
                    phrases=word.phrases,
                    listen=endpoint,
                    max_phrase_s=word.max_phrase_s,
                )

            label = f'palavra de ativação: "{word.phrases[0].title()}" (Whisper {word.check_model})'
        self.wake = listener
        self._wake_task = asyncio.create_task(_supervise(work, "palavra de ativação"))
        report(True, label)

    def pause_wake(self, paused: bool) -> None:
        if self.wake is not None:
            self.wake.enabled = not paused

    @property
    def wake_active(self) -> bool:
        return self.wake is not None and self.wake.enabled

    async def aclose(self) -> None:
        if self._wake_task is not None:
            self._wake_task.cancel()
            with _suppress_cancel():
                await self._wake_task
        if self.hotkeys is not None:
            self.hotkeys.stop()
        await self.triggers.aclose()
        await self.tts.aclose()
        await self.app.aclose()


class _suppress_cancel:  # noqa: N801 - usado como gerenciador de contexto
    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: type[BaseException] | None, *_: object) -> bool:
        return kind is asyncio.CancelledError


async def _supervise(work: Callable[[], Awaitable[None]], name: str) -> None:
    """Mantém uma tarefa de fundo viva: se cair (microfone desconectado), tenta de novo."""
    failures = 0
    while True:
        try:
            await work()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            log.exception("%s caiu (%d); tentando de novo", name, failures)
            await asyncio.sleep(min(60, 5 * failures))


async def build_voice_runtime(
    settings: Settings,
    *,
    keyboard: ConfirmationChannel,
    verbose: bool = False,
    theme: Theme | None = None,
    out: TextIO | None = None,
    on_phase: Callable[[Phase], None] | None = None,
    extra_notifier: Notifier | None = None,
) -> VoiceRuntime:
    """Monta tudo; lança ``TTSError``, ``DownloadError`` ou ``AudioDeviceError`` se faltar algo."""
    from shiro.infrastructure.voice.devices import SoundDeviceMicrophone, SoundDevicePlayer
    from shiro.infrastructure.voice.silero import SileroVAD

    voice = settings.voice
    tts, _ = tts_for(settings)
    stt = await whisper_for(settings)
    confirmation = VoiceConfirmation(keyboard=keyboard)
    voice_notifier = VoiceNotifier()
    notifier: Notifier = (
        FanOutNotifier(voice_notifier, extra_notifier) if extra_notifier else voice_notifier
    )
    app = await build_app(settings, confirmation=confirmation, notifier=notifier, channel="voice")
    session = VoiceSession(
        run_turn=app.agent.run_turn,
        stt=stt,
        tts=tts,
        player=SoundDevicePlayer(voice.output_device),
        microphone=SoundDeviceMicrophone(voice.input_device),
        detector=SileroVAD(),
        listen=endpoint_for(settings),
        cues=Cues.generate(voice.cue_volume),
        name=settings.general.assistant_name,
        volume=voice.tts.volume,
        verbose=verbose,
        theme=theme,
        out=out,
        follow_up_s=voice.wake_word.follow_up_window_s if wake_enabled(settings) else 0.0,
        on_phase=on_phase,
    )
    confirmation.attach(session)
    voice_notifier.attach(session)
    return VoiceRuntime(
        settings=settings, app=app, session=session, triggers=TriggerSource(), tts=tts, stt=stt
    )
