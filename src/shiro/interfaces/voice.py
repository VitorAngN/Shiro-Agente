"""Modo voz: falar com a SHIRO por atalho de teclado (``shiro voice``, marco 1b).

Fluxo de uma interação:

1. atalho (ou Enter no terminal) → bipe de "ouvindo";
2. o Silero VAD decide quando a frase terminou → Whisper transcreve;
3. o agente responde (Tier 0, modelo local ou nuvem);
4. a resposta é falada frase a frase: a próxima é sintetizada enquanto a atual toca.

O atalho de parar silencia a SHIRO e encerra a escuta na hora, mas **nunca**
cancela uma ação no meio: se o agente já está executando, ele termina e a
resposta só não é falada.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TextIO

from shiro.core.models import AgentResult, DecisionKind
from shiro.core.ports import ConfirmationChannel
from shiro.interfaces.text import describe_result
from shiro.interfaces.theme import Theme
from shiro.voice.audio import Audio, Cues
from shiro.voice.ports import Microphone, Player, SpeechDetector, SpeechToText, TextToSpeech
from shiro.voice.speech import for_speech, sentences, yes_or_no
from shiro.voice.vad import EndpointConfig, ListenControl, record_utterance

_EXIT = {"sair", "exit", "quit", "tchau"}
_STOP = {"p", "parar", "para", "stop"}


@dataclass(frozen=True)
class Trigger:
    kind: str  # "talk" | "stop" | "quit" | "text"
    text: str = ""


class TriggerSource:
    """Junta várias fontes de gatilho (atalhos globais, terminal) numa fila só."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    def put(self, trigger: Trigger) -> None:
        self._queue.put_nowait(trigger)

    def add(self, next_action: Callable[[], Awaitable[str]]) -> None:
        async def forward() -> None:
            while True:
                self.put(Trigger(await next_action()))

        self._tasks.append(asyncio.create_task(forward()))

    def add_terminal(self, reader: Callable[[], str]) -> None:
        """Enter fala, "p" para, "sair" encerra; qualquer outro texto vai direto ao agente."""

        async def forward() -> None:
            while True:
                try:
                    line = (await asyncio.to_thread(reader)).strip()
                except (EOFError, KeyboardInterrupt):
                    self.put(Trigger("quit"))
                    return
                lowered = line.casefold()
                if not line:
                    self.put(Trigger("talk"))
                elif lowered in _EXIT:
                    self.put(Trigger("quit"))
                    return
                elif lowered in _STOP:
                    self.put(Trigger("stop"))
                else:
                    self.put(Trigger("text", line))

        self._tasks.append(asyncio.create_task(forward()))

    async def next(self) -> Trigger:
        return await self._queue.get()

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


class Phase(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class VoiceSession:
    def __init__(
        self,
        *,
        run_turn: Callable[[str], Awaitable[AgentResult]],
        stt: SpeechToText,
        tts: TextToSpeech,
        player: Player,
        microphone: Microphone,
        detector: SpeechDetector,
        listen: EndpointConfig,
        cues: Cues,
        name: str,
        volume: float = 1.0,
        verbose: bool = False,
        theme: Theme | None = None,
        out: TextIO | None = None,
    ) -> None:
        self._run_turn = run_turn
        self._stt = stt
        self._tts = tts
        self._player = player
        self._microphone = microphone
        self._detector = detector
        self._listen = listen
        self._cues = cues
        self._name = name
        self._volume = volume
        self._verbose = verbose
        self.theme = theme or Theme(color=False)
        self._out = out or sys.stdout
        self.phase = Phase.IDLE
        self._control: ListenControl | None = None
        self._muted = False
        self._current: asyncio.Task[None] | None = None
        self._notices: list[str] = []

    # ------------------------------------------------------------------ laço

    async def run(self, triggers: TriggerSource) -> None:
        while True:
            trigger = await triggers.next()
            if trigger.kind == "quit":
                self.interrupt()
                await self._wait_current()
                return
            if trigger.kind == "stop":
                self.interrupt()
            elif trigger.kind == "talk":
                await self._on_talk()
            elif trigger.kind == "text":
                await self._start(self.interaction(trigger.text))

    async def _on_talk(self) -> None:
        if self.phase is Phase.LISTENING and self._control is not None:
            self._control.finish.set()  # segundo toque: terminei de falar
            return
        if self.phase is Phase.THINKING:
            self.print(self.theme.meta("(ainda pensando no pedido anterior)"))
            return
        if self.phase is Phase.SPEAKING:
            self.interrupt()  # interromper a SHIRO para falar de novo
            await self._wait_current()
        await self._start(self.interaction())

    async def _start(self, work: Awaitable[None]) -> None:
        await self._wait_current()
        self._muted = False

        async def guarded() -> None:
            try:
                await work
            except Exception as exc:
                self.print(self.theme.meta(f"(erro na voz: {type(exc).__name__}: {exc})"))
            finally:
                self.phase = Phase.IDLE
                await self._flush_notices()

        self._current = asyncio.create_task(guarded())

    async def _wait_current(self) -> None:
        if self._current is not None and not self._current.done():
            with contextlib.suppress(asyncio.CancelledError):
                await self._current

    def interrupt(self) -> None:
        """Para de falar e de ouvir. Uma ação em andamento termina, mas não é falada."""
        self._muted = True
        self._player.stop()
        if self._control is not None:
            self._control.cancel.set()

    # ------------------------------------------------------------------ interação

    async def interaction(self, typed: str | None = None) -> None:
        text = typed if typed is not None else await self.listen()
        if not text:
            return
        if typed is None:
            self.print(f"{self.theme.user_prompt()}{text}")
        self.phase = Phase.THINKING
        result = await self._run_turn(text)
        self.print(self.theme.assistant(self._name, result.text))
        if self._verbose:
            self.print(self.theme.meta(describe_result(result)))
        await self.say(result.text)

    async def listen(self) -> str | None:
        """Bipe, escuta uma frase e transcreve. ``None`` se não houve fala útil."""
        self._muted = False
        self.phase = Phase.LISTENING
        self._control = ListenControl()
        try:
            await self._player.play(self._cues.listening)
            audio = await record_utterance(
                self._microphone, self._detector, self._listen, self._control
            )
            cancelled = self._control.cancel.is_set()
        finally:
            self._control = None
            self.phase = Phase.IDLE
        if cancelled:
            return None
        if audio is None:
            self.print(self.theme.meta("(não ouvi nada)"))
            await self._player.play(self._cues.error)
            return None
        await self._player.play(self._cues.done)
        transcript = await self._stt.transcribe(audio)
        if self._verbose:
            seconds = f"{transcript.latency_ms / 1000:.2f}".replace(".", ",")
            self.print(self.theme.meta(f"[fala {audio.duration:.1f} s · transcrição {seconds} s]"))
        if not transcript.text:
            self.print(self.theme.meta("(não entendi)"))
            await self._player.play(self._cues.error)
            return None
        return transcript.text

    async def say(self, text: str) -> bool:
        """Fala frase a frase; a próxima é sintetizada enquanto a atual toca."""
        parts = sentences(for_speech(text))
        if not parts or self._muted:
            return False
        self.phase = Phase.SPEAKING
        upcoming: asyncio.Task[Audio] | None = asyncio.create_task(self._tts.synthesize(parts[0]))
        try:
            for index in range(len(parts)):
                assert upcoming is not None  # noqa: S101 - sempre há uma frase agendada aqui
                audio = await upcoming
                upcoming = None
                if index + 1 < len(parts):
                    upcoming = asyncio.create_task(self._tts.synthesize(parts[index + 1]))
                if self._muted or not await self._player.play(audio.scaled(self._volume)):
                    return False
            return True
        finally:
            if upcoming is not None:
                upcoming.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await upcoming
            self.phase = Phase.IDLE

    # ------------------------------------------------------------------ avisos

    def notice(self, message: str) -> None:
        """Aviso do agendador: falado agora se ela estiver livre, ou logo depois."""
        line = self.theme.paint(f"aviso ▸ {message}", (255, 210, 63), bold=True)
        self.print(f"\n{line}")
        self._notices.append(message)
        if self.phase is Phase.IDLE and (self._current is None or self._current.done()):
            self._current = asyncio.create_task(self._flush_notices())

    async def _flush_notices(self) -> None:
        while self._notices:
            message = self._notices.pop(0)
            self._muted = False
            await self.say(message)

    def print(self, text: str) -> None:
        print(text, file=self._out, flush=True)


class VoiceConfirmation:
    """Confirmação por voz ("sim" ou "não"); a física continua sendo no teclado."""

    def __init__(self, keyboard: ConfirmationChannel, attempts: int = 2) -> None:
        self._keyboard = keyboard
        self._attempts = attempts
        self._session: VoiceSession | None = None

    def attach(self, session: VoiceSession) -> None:
        self._session = session

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        session = self._session
        if session is None:
            return await self._keyboard.ask(prompt, kind)
        if kind is DecisionKind.CONFIRM_PHYSICAL:
            # Voz pode vir de um vídeo ou de outra pessoa: ação crítica só no teclado.
            await session.say("Essa precisa de confirmação no teclado.")
            return await self._keyboard.ask(prompt, kind)
        session.print(session.theme.paint(f"  ⚠ {prompt} (sim ou não)", (255, 210, 63)))
        try:
            return await self._ask_aloud(session, prompt)
        finally:
            session.phase = Phase.THINKING  # a confirmação acontece no meio do turno

    async def _ask_aloud(self, session: VoiceSession, prompt: str) -> bool:
        question = f"{prompt} Sim ou não?"
        for _ in range(self._attempts):
            if not await session.say(question):
                return False  # interrompida: na dúvida, não
            heard = await session.listen()
            if heard is None:
                break
            session.print(f"{session.theme.user_prompt()}{heard}")
            answer = yes_or_no(heard)
            if answer is not None:
                return answer
            question = "Não entendi. Sim ou não?"
        await session.say("Cancelado.")
        return False


class VoiceNotifier:
    """Lembretes e avisos de prazo falados (e escritos no terminal)."""

    def __init__(self) -> None:
        self._session: VoiceSession | None = None

    def attach(self, session: VoiceSession) -> None:
        self._session = session

    async def notify(self, title: str, message: str) -> None:
        if self._session is not None:
            self._session.notice(message)
