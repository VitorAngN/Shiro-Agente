from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from shiro.settings import ConfigError, Settings, load_settings
from tests.conftest import EXAMPLE_CONFIG


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_are_valid_and_safe() -> None:
    settings = Settings()

    assert settings.policy.read_only_mode is True
    assert settings.api.enabled is False
    assert settings.api.host == "127.0.0.1"
    assert settings.activities.local_only is True
    assert settings.memory.default_local_only is True


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nao-existe.toml") == Settings()


def test_example_config_is_valid() -> None:
    settings = load_settings(EXAMPLE_CONFIG)

    assert settings.general.assistant_name == "Shiro"
    assert settings.activities.default_due_time == time(23, 59)
    assert settings.policy.allowed_apps["spotify"] == "spotify.exe"


def test_environment_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write(tmp_path / "shiro.toml", "[agent]\nmax_steps = 6\nstep_timeout_s = 10\n")
    monkeypatch.setenv("SHIRO_AGENT__MAX_STEPS", "3")

    settings = load_settings(config)

    assert settings.agent.max_steps == 3
    assert settings.agent.step_timeout_s == 10


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    config = _write(tmp_path / "shiro.toml", "[agent]\nmax_stepz = 3\n")

    with pytest.raises(ConfigError, match="max_stepz"):
        load_settings(config)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    config = _write(tmp_path / "shiro.toml", "[agent\n")

    with pytest.raises(ConfigError, match="TOML inválido"):
        load_settings(config)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.10", "meu-pc.local"])  # noqa: S104
def test_api_refuses_non_loopback_hosts(tmp_path: Path, host: str) -> None:
    config = _write(tmp_path / "shiro.toml", f'[api]\nhost = "{host}"\n')

    with pytest.raises(ConfigError, match=r"api\.host"):
        load_settings(config)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_api_accepts_loopback_hosts(tmp_path: Path, host: str) -> None:
    config = _write(tmp_path / "shiro.toml", f'[api]\nhost = "{host}"\n')

    assert load_settings(config).api.host == host


def test_turn_timeout_must_cover_step_timeout(tmp_path: Path) -> None:
    config = _write(tmp_path / "shiro.toml", "[agent]\nstep_timeout_s = 30\nturn_timeout_s = 10\n")

    with pytest.raises(ConfigError, match="turn_timeout_s"):
        load_settings(config)


def test_audit_retention_cannot_be_shorter_than_messages(tmp_path: Path) -> None:
    config = _write(tmp_path / "shiro.toml", "[retention]\nmessages_days = 90\naudit_days = 30\n")

    with pytest.raises(ConfigError, match="audit_days"):
        load_settings(config)


def test_unknown_timezone_is_rejected(tmp_path: Path) -> None:
    config = _write(tmp_path / "shiro.toml", '[general]\ntimezone = "America/Atlantida"\n')

    with pytest.raises(ConfigError, match="fuso horário"):
        load_settings(config)


@pytest.mark.parametrize("offset", ["0h", "2x", "h", "-1d", "1.5h"])
def test_invalid_activity_alert_offsets(tmp_path: Path, offset: str) -> None:
    config = _write(tmp_path / "shiro.toml", f'[activities]\nalert_offsets = ["{offset}"]\n')

    with pytest.raises(ConfigError, match="alerta inválido"):
        load_settings(config)


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValueError, match="frozen"):
        settings.agent.max_steps = 99  # type: ignore[misc]
