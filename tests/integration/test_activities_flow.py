"""Atividades de ponta a ponta: o agente montado de verdade anota, conclui e lista no Tier 0."""

from __future__ import annotations

from pathlib import Path

from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from shiro.domain.models import Tier
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeProbe


async def test_full_agent_tier0_completes_and_lists(tmp_path: Path) -> None:
    # O modelo corta o prazo ("sexta"); a ferramenta ancora na fala ("pra sexta às 10h").
    llm = FakeProvider(
        [
            reply("", ("create_activity", {"title": "trabalho de cálculo", "due_text": "sexta"})),
            reply("Anotado para sexta."),
        ]
    )
    settings = Settings.model_validate({"policy": {"read_only_mode": False}})
    app = await build_app(
        settings,
        confirmation=type("Yes", (), {"ask": staticmethod(lambda *_: _true())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=llm,
        probe=FakeProbe(),
    )
    try:
        created = await app.agent.run_turn("o trabalho de cálculo é pra sexta às 10h, anota")
        assert created.tier is Tier.T1
        assert created.calls[0].result.ok
        assert "às 10h" in created.calls[0].result.content

        noted = await app.agent.run_turn("tenho prova de física dia 12 às 19h")
        assert noted.tier is Tier.T0
        assert noted.calls[0].call.arguments == {
            "title": "prova de física",
            "due_text": "dia 12 às 19h",
        }
        assert noted.calls[0].result.ok

        listed = await app.agent.run_turn("quais são minhas atividades?")
        assert listed.tier is Tier.T0
        assert "trabalho de cálculo" in listed.text

        done = await app.agent.run_turn("terminei o trabalho de cálculo")
        assert done.tier is Tier.T0
        assert done.text == "Concluída: trabalho de cálculo."
        assert len(llm.requests) == 2  # só a primeira criação passou pelo modelo
    finally:
        await app.aclose()


async def _true() -> bool:
    return True
