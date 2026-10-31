from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from shiro.core.bus import EventBus
from shiro.core.events import Event, TurnStarted
from shiro.core.models import RiskLevel
from shiro.tools.registry import ToolRegistry, compact_schema
from tests.fakes import FakeTool


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


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["play", "pause"] = Field(description="Ação")
    level: int = Field(default=10, ge=0, le=100)


def test_compact_schema_drops_titles() -> None:
    schema = compact_schema(_Args.model_json_schema())
    assert "title" not in schema
    assert "title" not in schema["properties"]["action"]
    assert schema["properties"]["action"]["enum"] == ["play", "pause"]
    assert schema["required"] == ["action"]


def test_registry_definitions_are_sorted_and_unique() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("zeta"))
    registry.register(FakeTool("alpha", risk=RiskLevel.R0))

    assert [d.name for d in registry.definitions()] == ["alpha", "zeta"]
    assert registry.get("alpha") is not None
    assert registry.get("nope") is None
    with pytest.raises(ValueError, match="duas vezes"):
        registry.register(FakeTool("alpha"))
