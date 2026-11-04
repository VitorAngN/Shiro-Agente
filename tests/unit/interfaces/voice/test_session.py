"""Sessão de voz com dublês: ouvir, pensar, falar, parar, confirmar e avisar."""

from __future__ import annotations

import asyncio

import pytest

from shiro.domain.models import AgentResult, DecisionKind
from shiro.interfaces.voice.session import (
    Phase,
    Trigger,
    TriggerSource,
    VoiceConfirmation,
    VoiceNotifier,
)
from tests.fakes.voice import (
    CUES,
    EndlessSpeech,
    FakePlayer,
    Keyboard,
    frames,
    make_session,
    until,
)


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


async def test_second_talk_while_listening_finishes_the_phrase() -> None:
    session, _, _, _, asked, _ = make_session(heard=["pula essa música"])
    microphone = EndlessSpeech()
    session._microphone = microphone  # pyright: ignore[reportPrivateUsage]
    triggers = TriggerSource()
    runner = asyncio.create_task(session.run(triggers))
    triggers.put(Trigger("talk"))
    # A fala só "começa" depois de 3 quadros; no Windows o relógio anda de 15 em 15 ms.
    await until(lambda: microphone.delivered >= 8)
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
