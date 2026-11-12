"""Aprendizado de ponta a ponta: ensina por fala, usa no Tier 0 e o modelo recebe o significado."""

from __future__ import annotations

from pathlib import Path

from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from shiro.domain.models import Role, Tier
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeProbe


async def test_teach_then_use(tmp_path: Path) -> None:
    local = FakeProvider([reply("Não sei dizer.")])
    settings = Settings.model_validate({"policy": {"read_only_mode": False}})
    app = await build_app(
        settings,
        confirmation=type("No", (), {"ask": staticmethod(lambda *_: _false())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=local,
        probe=FakeProbe(),
    )
    try:
        taught = await app.agent.run_turn("Quando eu disser hora certa, que horas são?")
        assert taught.tier is Tier.T0 and taught.calls[0].call.name == "learn_lesson"
        assert "hora certa" in taught.text

        used = await app.agent.run_turn("hora certa")
        assert used.tier is Tier.T0 and [c.call.name for c in used.calls] == ["get_time"]

        await app.agent.run_turn("aprende que o chefe é o professor de cálculo")
        await app.agent.run_turn("o chefe passou lista nova?")
        asked = [m.content for m in local.requests[-1].messages if m.role is Role.USER][-1]
        assert "professor de calculo" in asked  # o modelo recebe o significado

        listed = await app.agent.run_turn("o que você aprendeu?")
        assert "hora certa" in listed.text and "o chefe" in listed.text
        gone = await app.agent.run_turn("desaprende hora certa")
        assert gone.calls[0].result.ok
        assert (await app.agent.run_turn("o que você aprendeu?")).text.count("→") == 1
    finally:
        await app.aclose()


async def _false() -> bool:
    return False
