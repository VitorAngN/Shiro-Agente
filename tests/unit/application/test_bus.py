"""Barramento de eventos: entrega por tipo e isola falhas de um assinante."""

from __future__ import annotations

from shiro.application.bus import EventBus
from shiro.domain.events import Event, TurnStarted


async def test_bus_delivers_by_type_and_isolates_failures() -> None:
    bus = EventBus()
    received: list[str] = []

    async def broken(event: Event) -> None:
        raise RuntimeError("boom")

    async def on_turn(event: TurnStarted) -> None:
        received.append(event.text)

    bus.subscribe(Event, broken)
    bus.subscribe(TurnStarted, on_turn)
    await bus.publish(TurnStarted(trace_id="t", session_id="s", channel="text", text="oi"))
    await bus.publish(Event(trace_id="t2"))

    assert received == ["oi"]
