"""Montagem completa do app e modo texto, sem Windows, sem GPU e sem internet."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from shiro.bootstrap.app import build_app
from shiro.bootstrap.tools import Desktop
from shiro.config.settings import Settings, load_settings
from shiro.domain.models import DecisionKind, Tier
from shiro.interfaces.cli.main import main
from shiro.interfaces.text.session import TextSession
from tests.fakes.agent import FakeProvider, reply
from tests.fakes.desktop import FakeLauncher, FakeProbe, FakeVolume


class Keys:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    async def press(self, action: Any) -> None:
        self.pressed.append(action)


def settings_with_apps(tmp_path: Path, *, read_only: bool = False) -> Settings:
    config = tmp_path / "shiro.toml"
    config.write_text(
        f"""
[general]
city = "Curitiba"

[policy]
read_only_mode = {str(read_only).lower()}

[policy.allowed_apps.spotify]
launch = "spotify:"
process = "Spotify.exe"
name = "Spotify"
""",
        encoding="utf-8",
    )
    return load_settings(config)


class Answers:
    def __init__(self, *answers: bool) -> None:
        self._answers = list(answers)

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        return self._answers.pop(0) if self._answers else False


@pytest.fixture
def offline_http() -> Iterator[httpx.AsyncClient]:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede nos testes", request=request)

    yield httpx.AsyncClient(transport=httpx.MockTransport(refuse))


async def test_full_app_tier0_and_llm_turns_are_persisted(
    tmp_path: Path, offline_http: httpx.AsyncClient
) -> None:
    volume, launcher, keys = FakeVolume(40), FakeLauncher(), Keys()
    llm = FakeProvider([reply("", ("system_info", {"metric": "ram"})), reply("Uns 9 GB.")])
    app = await build_app(
        settings_with_apps(tmp_path),
        confirmation=Answers(),
        database_path=tmp_path / "data" / "shiro.db",
        desktop=Desktop(volume=volume, media=keys, launcher=launcher),
        local_llm=llm,
        http=offline_http,
        probe=FakeProbe(),
    )
    try:
        assert set(app.registry.names()) >= {
            "change_volume",
            "close_app",
            "complete_activity",
            "create_activity",
            "create_reminder",
            "get_time",
            "get_weather",
            "list_activities",
            "media_control",
            "open_app",
            "set_volume",
            "system_info",
        }

        first = await app.agent.run_turn("Shiro, abre o Spotify")
        assert first.tier is Tier.T0
        assert launcher.launched == ["spotify:"]

        second = await app.agent.run_turn("volume em 25")
        assert volume.level == 25
        assert second.text == "Volume em 25."

        third = await app.agent.run_turn("quanta memória eu tô usando?")
        assert third.tier is Tier.T1
        assert third.text == "Uns 9 GB."

        assert await app.audit.verify() is None
        async with app.database.connection.execute(
            "SELECT COUNT(*) FROM message WHERE role = 'assistant'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 3  # type: ignore[index]
    finally:
        await app.aclose()


async def test_without_desktop_only_portable_tools_are_registered(
    tmp_path: Path, offline_http: httpx.AsyncClient
) -> None:
    app = await build_app(
        Settings(),
        confirmation=Answers(),
        database_path=":memory:",
        desktop=Desktop(),
        local_llm=FakeProvider([]),
        http=offline_http,
        probe=FakeProbe(),
    )
    try:
        names = set(app.registry.names())
        assert {"get_time", "get_weather", "system_info", "create_activity"} <= names
        assert not names & {"set_volume", "media_control", "open_app", "close_app"}
        result = await app.agent.run_turn("volume em 20")  # Tier 0 sem a ferramenta
        assert "não existe ou está desativada" in result.text
    finally:
        await app.aclose()


async def test_read_only_mode_asks_before_acting(
    tmp_path: Path, offline_http: httpx.AsyncClient
) -> None:
    volume = FakeVolume(40)
    app = await build_app(
        settings_with_apps(tmp_path, read_only=True),
        confirmation=Answers(False),
        database_path=":memory:",
        desktop=Desktop(volume=volume),
        local_llm=FakeProvider([]),
        http=offline_http,
        probe=FakeProbe(),
    )
    try:
        result = await app.agent.run_turn("volume em 10")
        assert volume.level == 40
        assert result.text == "Tudo bem, não fiz nada."
    finally:
        await app.aclose()


async def test_text_session_loop(tmp_path: Path, offline_http: httpx.AsyncClient) -> None:
    app = await build_app(
        settings_with_apps(tmp_path),
        confirmation=Answers(),
        database_path=":memory:",
        desktop=Desktop(volume=FakeVolume()),
        local_llm=FakeProvider([reply("Oi! Em que posso ajudar?")]),
        http=offline_http,
        probe=FakeProbe(),
    )
    lines = iter(["oi", "", "volume em 30", "sair"])
    out = io.StringIO()
    session = TextSession(
        app.agent.run_turn, name="Shiro", verbose=True, out=out, reader=lambda _: next(lines)
    )
    try:
        await session.loop()
    finally:
        await app.aclose()

    text = out.getvalue()
    assert "shiro ▸ Oi! Em que posso ajudar?" in text
    assert "shiro ▸ Volume em 30." in text
    assert "[T0 · regra" in text
    assert "set_volume ✓" in text


def test_chat_command_end_to_end(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, isolated_env: Path
) -> None:
    import shiro.bootstrap.app as composition
    from shiro.domain.ports import LLMError

    class OllamaDown(FakeProvider):
        async def warm_up(self, request: Any) -> None:
            raise LLMError("connection refused")

    original = composition.build_app
    volume = FakeVolume(40)

    async def fake_build_app(settings: Settings, **kwargs: Any) -> Any:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        return await original(
            settings,
            confirmation=kwargs["confirmation"],
            desktop=Desktop(volume=volume),
            local_llm=OllamaDown([]),
            http=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
            probe=FakeProbe(),
        )

    monkeypatch.setattr(composition, "build_app", fake_build_app)
    config = isolated_env / "config" / "shiro.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[policy]\nread_only_mode = false\n", encoding="utf-8")

    assert main(["chat", "-v", "-m", "volume em 30"]) == 0

    out = capsys.readouterr().out
    assert "modelo local offline" in out
    assert "auditoria íntegra" in out
    assert "shiro ▸ Volume em 30." in out
    assert volume.level == 30
    assert (isolated_env / "data" / "shiro.db").is_file()
    assert (isolated_env / "data" / "logs" / "shiro.log").is_file()
