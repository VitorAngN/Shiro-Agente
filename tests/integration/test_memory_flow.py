"""Memória de ponta a ponta: o fato entra no contexto do modelo local e nunca vai para a nuvem."""

from __future__ import annotations

from pathlib import Path

from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from shiro.domain.models import Role, Tier
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeProbe


async def test_agent_uses_memories_and_keeps_them_local(tmp_path: Path) -> None:
    local = FakeProvider([reply("Você torce pro Coritiba.")])
    cloud = FakeProvider([reply("não deveria ser chamado")], name="gemini")
    settings = Settings.model_validate({"policy": {"read_only_mode": False}})
    app = await build_app(
        settings,
        confirmation=type("No", (), {"ask": staticmethod(lambda *_: _false())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=local,
        cloud_llm=cloud,
        probe=FakeProbe(),
    )
    try:
        saved = await app.agent.run_turn("lembra que eu torço pro Coritiba")
        assert saved.tier is Tier.T0 and saved.calls[0].result.ok
        answer = await app.agent.run_turn("pra qual time do Coritiba eu torço?")
        assert answer.tier is Tier.T1
        request = local.requests[0]
        assert any(m.role is Role.SYSTEM and "Coritiba" in m.content for m in request.messages[1:])
        assert cloud.requests == []
    finally:
        await app.aclose()


async def _false() -> bool:
    return False
