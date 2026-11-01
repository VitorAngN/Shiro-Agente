"""Sessão de voz com dublês: ouvir, pensar, falar, parar, confirmar e avisar."""

from __future__ import annotations

import asyncio
import contextlib
import io
from collections.abc import AsyncIterator, Callable

import numpy as np
import pytest

from shiro.cli_voice import command_meaning, word_error_rate
from shiro.core.models import AgentResult, DecisionKind, Tier
from shiro.interfaces.voice import (
    Phase,
    Trigger,
    TriggerSource,
    VoiceConfirmation,
    VoiceNotifier,
    VoiceSession,
)
from shiro.voice.audio import Audio, Cues, tone
from shiro.voice.ports import Transcript
from shiro.voice.vad import EndpointConfig
from tests.unit.test_voice import FakeMic, ScriptedDetector, frames

SPEECH = frames(3) + frames(10, 0.9) + frames(30)


class FakeSTT:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.heard: list[float] = []

    async def load(self) -> None:
        return None

    async def transcribe(self, audio: Audio) -> Transcript:
        self.heard.append(audio.duration)
        return Transcript(text=self.texts.pop(0) if self.texts else "", audio_s=1, latency_ms=5)


class FakeTTS:
    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> Audio:
        self.spoken.append(text)
        await asyncio.sleep(0)
        return Audio(np.full(len(text), 0.5, dtype=np.float32), 24_000)

    async def aclose(self) -> None:
        return None


class FakePlayer:
    def __init__(self, interrupt_after: int | None = None) -> None:
        self.played: list[Audio] = []
        self.stopped = False
        self._interrupt_after = interrupt_after
        self.on_play: Callable[[], None] | None = None

    async def play(self, audio: Audio) -> bool:
        self.stopped = False
        self.played.append(audio)
        await asyncio.sleep(0)
        if self.on_play is not None:
            self.on_play()
        if self._interrupt_after is not None and len(self.played) >= self._interrupt_after:
            self.stopped = True
        return not self.stopped

    def stop(self) -> None:
        self.stopped = True


async def until(condition: Callable[[], bool], limit_s: float = 2.0) -> None:
    """Espera a sessão chegar a um estado (as tarefas dela rodam em paralelo)."""
    async with asyncio.timeout(limit_s):
        while not condition():  # noqa: ASYNC110 - estado da sessão, não um evento
            await asyncio.sleep(0.005)


CUES = Cues(listening=tone(880, 50), done=tone(740, 50), error=tone(300, 50))


def turn(text: str) -> AgentResult:
    return AgentResult(text=text, tier=Tier.T0, calls=(), steps=0)


def make_session(
    *,
    heard: list[str],
    reply: str = "Volume em 20%.",
    player: FakePlayer | None = None,
    mic_blocks: list[np.ndarray] | None = None,
) -> tuple[VoiceSession, FakeSTT, FakeTTS, FakePlayer, list[str], io.StringIO]:
    asked: list[str] = []

    async def run_turn(text: str) -> AgentResult:
        asked.append(text)
        await asyncio.sleep(0)
        return turn(reply)

    stt, tts, out = FakeSTT(heard), FakeTTS(), io.StringIO()
    player = player or FakePlayer()
    session = VoiceSession(
        run_turn=run_turn,
        stt=stt,
        tts=tts,
        player=player,
        microphone=FakeMic(mic_blocks if mic_blocks is not None else SPEECH),
        detector=ScriptedDetector(),
        listen=EndpointConfig(end_silence_ms=320),
        cues=CUES,
        name="Shiro",
        verbose=True,
        out=out,
    )
    return session, stt, tts, player, asked, out


async def test_one_spoken_interaction_end_to_end() -> None:
    session, stt, tts, player, asked, out = make_session(
        heard=["abaixa o volume pra 20"], reply="Volume em 20%. Pronto pra mais."
    )

    await session.interaction()

    assert asked == ["abaixa o volume pra 20"]
    assert stt.heard and stt.heard[0] > 0.3
    assert tts.spoken == ["Volume em 20 por cento. Pronto pra mais."]
    assert player.played[0] is CUES.listening and player.played[1] is CUES.done
    assert len(player.played) == 3
    text = out.getvalue()
    assert "abaixa o volume pra 20" in text and "shiro ▸ Volume em 20%." in text
    assert "transcrição" in text  # modo detalhado mostra os tempos
    assert session.phase is Phase.IDLE


async def test_silence_and_noise_are_reported_not_sent() -> None:
    quiet, _, _, player, asked, out = make_session(heard=[], mic_blocks=frames(300))
    await quiet.interaction()
    assert asked == [] and "não ouvi nada" in out.getvalue()
    assert player.played[-1] is CUES.error

    noise, _, _, _, asked2, out2 = make_session(heard=[""])
    await noise.interaction()
    assert asked2 == [] and "não entendi" in out2.getvalue()


async def test_long_replies_are_spoken_sentence_by_sentence_and_can_be_stopped() -> None:
    reply = "Primeira frase bem comprida aqui. Segunda frase bem comprida aqui. Terceira frase."
    session, _, tts, player, _, _ = make_session(heard=[], reply=reply)
    assert await session.say(reply)
    assert len(tts.spoken) == 3 and len(player.played) == 3

    stopping = FakePlayer(interrupt_after=1)
    session2, _, tts2, _, _, _ = make_session(heard=[], reply=reply, player=stopping)
    assert not await session2.say(reply)
    assert len(stopping.played) == 1  # parou na primeira frase
    assert len(tts2.spoken) <= 2  # a próxima pode ter começado, mas não tocou


async def test_stop_during_thinking_lets_the_action_finish_silently() -> None:
    session, _, tts, _, asked, out = make_session(heard=["abre o spotify"])
    original = session._run_turn  # pyright: ignore[reportPrivateUsage]

    async def slow_turn(text: str) -> AgentResult:
        session.interrupt()  # usuário apertou "parar" enquanto o agente executava
        return await original(text)

    session._run_turn = slow_turn  # pyright: ignore[reportPrivateUsage]
    await session.interaction()

    assert asked == ["abre o spotify"]  # a ação foi até o fim
    assert tts.spoken == []  # mas a resposta não foi falada
    assert "shiro ▸" in out.getvalue()  # e aparece na tela


async def test_run_loop_handles_text_talk_stop_and_quit() -> None:
    session, _, tts, player, asked, _ = make_session(heard=["que horas são"])
    triggers = TriggerSource()
    triggers.put(Trigger("text", "oi, tudo bem?"))
    runner = asyncio.create_task(session.run(triggers))
    await until(lambda: bool(tts.spoken))
    triggers.put(Trigger("talk"))
    await until(lambda: len(asked) == 2)
    await until(lambda: session.phase is Phase.IDLE)
    triggers.put(Trigger("stop"))
    triggers.put(Trigger("quit"))
    await asyncio.wait_for(runner, 2)
    await triggers.aclose()

    assert asked == ["oi, tudo bem?", "que horas são"]
    assert player.stopped


class EndlessSpeech(FakeMic):
    """Fala sem parar: só o segundo toque no atalho encerra a escuta."""

    def __init__(self) -> None:
        super().__init__([])

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[np.ndarray]]:
        async def generate() -> AsyncIterator[np.ndarray]:
            while True:
                await asyncio.sleep(0.001)
                yield np.full(512, 0.9, dtype=np.float32)

        yield generate()


async def test_second_talk_while_listening_finishes_the_phrase() -> None:
    session, _, _, _, asked, _ = make_session(heard=["pula essa música"])
    session._microphone = EndlessSpeech()  # pyright: ignore[reportPrivateUsage]
    triggers = TriggerSource()
    runner = asyncio.create_task(session.run(triggers))
    triggers.put(Trigger("talk"))
    await until(lambda: session.phase is Phase.LISTENING)
    await asyncio.sleep(0.01)
    triggers.put(Trigger("talk"))  # "terminei de falar"
    await until(lambda: bool(asked))
    triggers.put(Trigger("quit"))
    await asyncio.wait_for(runner, 2)
    assert asked == ["pula essa música"]


async def test_terminal_trigger_parsing() -> None:
    lines = iter(["", "p", "abre o spotify", "sair"])
    triggers = TriggerSource()
    triggers.add_terminal(lambda: next(lines))
    got = [await asyncio.wait_for(triggers.next(), 1) for _ in range(4)]
    await triggers.aclose()
    assert got == [
        Trigger("talk"),
        Trigger("stop"),
        Trigger("text", "abre o spotify"),
        Trigger("quit"),
    ]

    hotkeys = iter(["talk", "stop"])

    async def next_hotkey() -> str:
        await asyncio.sleep(0)
        return next(hotkeys)

    source = TriggerSource()
    source.add(next_hotkey)
    assert await asyncio.wait_for(source.next(), 1) == Trigger("talk")
    await source.aclose()


async def test_notices_are_spoken_when_idle() -> None:
    session, _, tts, _, _, out = make_session(heard=[])
    notifier = VoiceNotifier()
    await notifier.notify("Lembrete", "sem sessão, só some")  # antes de ligar: ignora
    notifier.attach(session)
    await notifier.notify("Lembrete", "Lembrete: tirar a roupa do varal.")
    await asyncio.sleep(0.05)
    assert tts.spoken == ["Lembrete: tirar a roupa do varal."]
    assert "aviso ▸" in out.getvalue()


class Keyboard:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked: list[tuple[str, DecisionKind]] = []

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        self.asked.append((prompt, kind))
        return self.answer


@pytest.mark.parametrize(
    ("heard", "expected", "rounds"),
    [
        (["sim, pode"], True, 1),
        (["não"], False, 1),
        (["hã?", "pode sim"], True, 2),
        (["talvez", "sei lá"], False, 2),
    ],
)
async def test_voice_confirmation(heard: list[str], expected: bool, rounds: int) -> None:
    session, stt, tts, _, _, _ = make_session(heard=list(heard))
    keyboard = Keyboard(answer=False)
    confirmation = VoiceConfirmation(keyboard=keyboard)
    confirmation.attach(session)
    session.phase = Phase.THINKING

    answer = await confirmation.ask("Fechar o Discord?", DecisionKind.CONFIRM_VOICE)

    assert answer is expected
    assert tts.spoken[0] == "Fechar o Discord? Sim ou não?"
    assert len(stt.heard) == rounds
    assert keyboard.asked == []
    assert session.phase is Phase.THINKING  # o turno continua depois da confirmação


async def test_physical_confirmation_goes_to_the_keyboard() -> None:
    session, _, tts, _, _, _ = make_session(heard=["sim"])
    keyboard = Keyboard(answer=True)
    confirmation = VoiceConfirmation(keyboard=keyboard)

    # sem sessão (ainda iniciando): teclado
    assert await confirmation.ask("Apagar?", DecisionKind.CONFIRM_VOICE)
    confirmation.attach(session)
    assert await confirmation.ask("Desligar o PC?", DecisionKind.CONFIRM_PHYSICAL)

    assert [kind for _, kind in keyboard.asked] == [
        DecisionKind.CONFIRM_VOICE,
        DecisionKind.CONFIRM_PHYSICAL,
    ]
    assert tts.spoken == ["Essa precisa de confirmação no teclado."]


async def test_confirmation_without_answer_cancels() -> None:
    session, _, tts, _, _, _ = make_session(heard=[], mic_blocks=frames(300))
    confirmation = VoiceConfirmation(keyboard=Keyboard(answer=True))
    confirmation.attach(session)
    assert not await confirmation.ask("Fechar o Chrome?", DecisionKind.CONFIRM_VOICE)
    assert tts.spoken[-1] == "Cancelado."


def test_word_error_rate() -> None:
    assert word_error_rate("abre o spotify", "Abre o Spotify.") == 0
    assert word_error_rate("abre o spotify", "abre spotify") == pytest.approx(1 / 3)
    assert word_error_rate("", "") == 0
    assert word_error_rate("", "oi") == 1


def test_command_meaning_compares_deadlines_by_moment() -> None:
    from datetime import datetime

    from shiro.activities.rules import ActivityRules
    from shiro.core.router import IntentRouter
    from tests.fakes import SAO_PAULO

    now = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
    router = IntentRouter(apps={}, cloud_triggers=(), rules=(ActivityRules(lambda: now),))

    def meaning(text: str) -> object:
        return command_meaning(router.match_tier0(text), now)

    spoken = "tenho prova de física dia doze às sete da noite"
    assert meaning(spoken) == meaning("Tenho prova de física dia 12 a 7 da noite.")
    assert meaning(spoken) != meaning("Tenho prova de física dia 12 às 7 da manhã.")
    assert meaning("me lembra de tirar a roupa do varal às seis") == meaning(
        "Me lembra de tirar a roupa do varal a 6."
    )
    assert meaning("como vai") is None
