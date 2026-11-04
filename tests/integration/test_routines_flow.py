"""Rotina "modo estudo" de ponta a ponta, cada passo pela política."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shiro.application.routines import ListRoutinesTool
from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from shiro.domain.models import Tier
from shiro.domain.ports import ToolContext
from tests.fakes.agent import SAO_PAULO, FakeProvider
from tests.fakes.desktop import FakeLauncher, FakeProbe, FakeVolume
from tests.fakes.routines import study_routine

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
CTX = ToolContext(trace_id="t", now=NOW)


async def test_study_mode_end_to_end(tmp_path: Path) -> None:
    launcher, volume = FakeLauncher(), FakeVolume()
    settings = Settings.model_validate(
        {
            "policy": {
                "read_only_mode": False,
                "allowed_apps": {
                    "discord": {"launch": "discord:", "process": "Discord.exe"},
                    "vscode": "code",
                },
                "allowed_folders": [],
            },
            "routines": {k: v.model_dump() for k, v in study_routine().items()},
        }
    )
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(volume=volume, launcher=launcher),
        local_llm=FakeProvider([]),
        probe=FakeProbe(),
    )
    try:
        assert app.problems and "quebrada" in app.problems[0]
        result = await app.agent.run_turn("ativa o modo estudo")
        assert result.tier is Tier.T0
        assert [c.call.name for c in result.calls] == ["close_app", "open_app", "set_volume"]
        assert all(c.result.ok for c in result.calls)
        assert launcher.launched == ["code"] and volume.level == 30
        listed = await ListRoutinesTool({}).run(ListRoutinesTool.spec.args_model(), CTX)
        assert "Nenhuma rotina" in listed.content
        assert app.registry.get("list_files") is None  # sem pasta liberada, sem ferramentas
    finally:
        await app.aclose()


async def _true() -> bool:
    return True
