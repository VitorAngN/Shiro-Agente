"""Esperas e vigias: rodam os passos na hora certa e avisam."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest

from shiro.application.watch.service import Steps, Waits
from shiro.application.watch.tools import wait_tools
from shiro.domain.models import AgentResult, Tier
from shiro.domain.ports import ToolContext
from tests.unit.application.skills.test_skills import NOW


class Recorder:
    def __init__(self) -> None:
        self.ran: list[Steps] = []
        self.notes: list[str] = []

    async def run(self, steps: Steps) -> AgentResult:
        self.ran.append(steps)
        return AgentResult(text="Aceitei a partida.", tier=Tier.T0)

    async def notify(self, text: str) -> None:
        self.notes.append(text)


def check(tool: str, args: dict[str, Any]) -> str | None:
    return None if tool in {"click_on", "press_keys"} else "não conheço essa ação"


async def test_timer_runs_steps_and_notifies() -> None:
    rec = Recorder()
    waits = Waits(rec.run, rec.notify)
    made = waits.after(0.01, [("press_keys", {"keys": "k"})], "pausar o vídeo")
    assert not isinstance(made, str)
    await asyncio.sleep(0.05)
    assert rec.ran == [[("press_keys", {"keys": "k"})]] and rec.notes == ["Aceitei a partida."]
    assert waits.active() == []


async def test_watch_fires_when_target_appears_and_gives_up_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shiro.application.watch import service

    monkeypatch.setattr(service, "MIN_EVERY_S", 0.0)
    rec = Recorder()
    looks = iter([False, False, True])

    async def seen(target: str) -> bool:
        return next(looks)

    waits = Waits(rec.run, rec.notify, seen)
    waits.when_seen(
        "Aceitar", [("click_on", {"target": "Aceitar"})], "aceitar", every_s=0, timeout_s=5
    )
    await asyncio.sleep(0.05)
    assert len(rec.ran) == 1

    async def never(target: str) -> bool:
        return False

    late = Waits(rec.run, rec.notify, never)
    late.when_seen("Aceitar", [("click_on", {"target": "x"})], "aceitar", every_s=0, timeout_s=0.01)
    await asyncio.sleep(0.05)
    assert rec.notes[-1].startswith("Desisti de esperar")


async def test_tools_validate_steps_and_cancel() -> None:
    rec = Recorder()

    async def never(target: str) -> bool:
        await asyncio.sleep(10)
        return False

    waits = Waits(rec.run, rec.notify, never)
    tools = {tool.spec.name: tool for tool in wait_tools(waits, check)}
    ctx = ToolContext(trace_id="t", now=NOW)
    when = tools["when_visible"]
    bad = when.spec.args_model(
        target="Aceitar", steps_json=json.dumps([{"tool": "format", "args": {}}]), description="x"
    )
    assert "não conheço" in str(cast(Any, when).problem(bad))
    good = when.spec.args_model(
        target="Aceitar",
        steps_json=json.dumps([{"tool": "click_on", "args": {"target": "Aceitar"}}]),
        description="aceitar a partida",
    )
    made = await when.run(good, ctx)
    assert made.ok and len(waits.active()) == 1
    listed = await tools["list_waits"].run(tools["list_waits"].spec.args_model(), ctx)
    assert "aceitar a partida" in listed.content
    cancel = await tools["cancel_waits"].run(tools["cancel_waits"].spec.args_model(), ctx)
    assert cancel.ok
    await asyncio.sleep(0.01)
    assert waits.active() == []
