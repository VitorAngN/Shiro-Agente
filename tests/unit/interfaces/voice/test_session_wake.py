"""Sessão de voz com palavra de ativação e janela de continuação."""

from __future__ import annotations

import asyncio

from shiro.interfaces.voice.session import Phase, Trigger, TriggerSource
from tests.fakes.voice import frames, make_session, until, utterance


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
