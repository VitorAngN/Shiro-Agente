"""Nuvem na montagem real: desligada sem chave, ligada com chave e de volta ao local se falhar."""

from __future__ import annotations

from pathlib import Path

from shiro.bootstrap.app import build_app
from shiro.bootstrap.llm import build_cloud_llm
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings
from shiro.domain.models import Tier
from shiro.domain.ports import LLMError
from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.usage import SqliteUsageLedger
from shiro.infrastructure.system import secrets
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeProbe


async def test_cloud_is_off_without_key_and_on_with_key() -> None:
    database = await Database.open(":memory:")
    ledger = SqliteUsageLedger(database)

    provider, status = build_cloud_llm(Settings(), ledger)
    assert provider is None
    assert "shiro secrets set gemini" in status

    secrets.set_api_key("gemini", "chave-de-teste")
    provider, status = build_cloud_llm(Settings(), ledger)
    assert provider is not None
    assert status == "nuvem: gemini/gemini-3.5-flash-lite"

    off = Settings.model_validate({"llm": {"cloud": {"enabled": False}}})
    assert build_cloud_llm(off, ledger)[0] is None
    await database.close()


async def test_cloud_failure_falls_back_to_local(tmp_path: Path) -> None:
    app = await build_app(
        Settings(),
        confirmation=type("No", (), {"ask": staticmethod(lambda *_: False)})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=FakeProvider([reply("Resposta local.")], name="ollama"),
        cloud_llm=FakeProvider([LLMError("cota esgotada")], name="gemini"),
        probe=FakeProbe(),
    )
    try:
        result = await app.agent.run_turn("pensa bem: como organizo a semana?")
        assert result.tier is Tier.T1
        assert result.text == "Resposta local."
    finally:
        await app.aclose()
