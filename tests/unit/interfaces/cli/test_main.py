"""Comando shiro: versão, config, secrets e chat com configuração inválida."""

from __future__ import annotations

from pathlib import Path

import pytest

from shiro import __version__
from shiro.infrastructure.system import secrets
from shiro.interfaces.cli.main import _secrets, main  # pyright: ignore[reportPrivateUsage]


def test_chat_command_reports_invalid_config(
    capsys: pytest.CaptureFixture[str], isolated_env: Path
) -> None:
    config = isolated_env / "config" / "shiro.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[api]\nhost = "0.0.0.0"\n', encoding="utf-8")

    assert main(["chat", "-m", "oi"]) == 1
    assert "configuração inválida" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"shiro {__version__}"


def test_without_command_explains_current_phase(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "shiro chat" in capsys.readouterr().out


def test_config_path_reports_missing_file(
    capsys: pytest.CaptureFixture[str], isolated_env: Path
) -> None:
    assert main(["config", "path"]) == 0

    out = capsys.readouterr().out
    assert str(isolated_env / "config" / "shiro.toml") in out
    assert "ainda não existe" in out


def test_config_check_accepts_valid_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = tmp_path / "valido.toml"
    config.write_text('[llm.local]\nmodel = "qwen3:4b-instruct"\n', encoding="utf-8")

    assert main(["config", "check", "--file", str(config)]) == 0
    assert "configuração válida" in capsys.readouterr().out


def test_config_check_rejects_invalid_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    config = tmp_path / "invalido.toml"
    config.write_text('[api]\nhost = "0.0.0.0"\n', encoding="utf-8")

    assert main(["config", "check", "--file", str(config)]) == 1
    assert "api.host" in capsys.readouterr().out


def test_config_check_uses_default_location(
    capsys: pytest.CaptureFixture[str], isolated_env: Path
) -> None:
    assert main(["config", "check"]) == 0
    assert "modo somente leitura: sim" in capsys.readouterr().out


def test_secrets_command(capsys: pytest.CaptureFixture[str]) -> None:
    import argparse

    set_args = argparse.Namespace(secrets_command="set", provider="gemini")
    assert _secrets(set_args, prompt=lambda _: "minha-chave") == 0
    assert "guardada" in capsys.readouterr().out
    assert secrets.get_api_key("gemini") == "minha-chave"

    assert main(["secrets", "status"]) == 0
    out = capsys.readouterr().out
    assert "gemini: configurada (cofre)" in out
    assert "minha-chave" not in out  # a chave nunca aparece

    assert main(["config", "check"]) == 0
    assert "chave no cofre" in capsys.readouterr().out

    assert main(["secrets", "delete", "gemini"]) == 0
    assert "apagada" in capsys.readouterr().out
    assert _secrets(set_args, prompt=lambda _: "") == 1
