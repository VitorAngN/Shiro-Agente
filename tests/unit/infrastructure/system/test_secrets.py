"""Cofre de chaves: ida e volta e prioridade da variável de ambiente."""

from __future__ import annotations

import pytest

from shiro.infrastructure.system import secrets


def test_secrets_round_trip_and_env_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    assert secrets.get_api_key("gemini") is None
    assert secrets.key_source("gemini") is None

    secrets.set_api_key("gemini", "  do-cofre  ")
    assert secrets.get_api_key("gemini") == "do-cofre"
    assert secrets.key_source("gemini") == "cofre"

    monkeypatch.setenv("GEMINI_API_KEY", "do-ambiente")
    assert secrets.get_api_key("gemini") == "do-ambiente"
    assert secrets.key_source("gemini") == "ambiente"

    assert secrets.delete_api_key("gemini")
    assert not secrets.delete_api_key("gemini")
    with pytest.raises(ValueError, match="vazia"):
        secrets.set_api_key("gemini", "   ")
    with pytest.raises(ValueError, match="desconhecido"):
        secrets.get_api_key("deepseek")
