"""O agente mantém os grupos de ferramentas dos últimos turnos para continuações."""

from __future__ import annotations

from pathlib import Path

from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeProbe


async def _true() -> bool:
    return True


async def test_agent_remembers_recent_groups_for_follow_ups(tmp_path: Path) -> None:
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "a.pdf").write_text("x")
    local = FakeProvider(
        [
            reply("", ("list_files", {})),
            reply("Tem um PDF."),
            reply("Ok."),
        ]
    )
    settings = Settings.model_validate(
        {"policy": {"read_only_mode": False, "allowed_folders": [str(tmp_path / "Downloads")]}}
    )
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=local,
        probe=FakeProbe(),
    )
    try:
        await app.agent.run_turn("o que tem nos meus downloads?")
        await app.agent.run_turn("e qual é o mais novo?")
        first = {d.name for d in local.requests[0].tools}
        follow_up = {d.name for d in local.requests[2].tools}
        assert "list_files" in first and "list_files" in follow_up
        app.agent.reset()
        assert app.agent._recent_groups() == frozenset()  # pyright: ignore[reportPrivateUsage]
    finally:
        await app.aclose()
