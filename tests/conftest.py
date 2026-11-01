"""Configuração comum dos testes.

Todo teste roda isolado: sem variáveis ``SHIRO_*`` do ambiente real e com
configuração e dados apontando para pastas temporárias. Assim os testes nunca
leem nem escrevem nos arquivos pessoais de quem está rodando.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import keyring
import keyring.backend
import keyring.errors
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "shiro.example.toml"


class MemoryKeyring(keyring.backend.KeyringBackend):
    """Cofre em memória: os testes nunca tocam no cofre real do sistema."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for key in list(os.environ):
        if key.startswith("SHIRO_") or key.endswith("_API_KEY"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SHIRO_CONFIG", str(tmp_path / "config" / "shiro.toml"))
    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path / "data"))
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield tmp_path
    keyring.set_keyring(previous)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skips = {
        "windows": (sys.platform != "win32", "requer Windows"),
        "ollama": (os.environ.get("SHIRO_TEST_OLLAMA") != "1", "defina SHIRO_TEST_OLLAMA=1"),
        "gpu": (os.environ.get("SHIRO_TEST_GPU") != "1", "defina SHIRO_TEST_GPU=1"),
    }
    for item in items:
        for marker, (should_skip, reason) in skips.items():
            if should_skip and item.get_closest_marker(marker):
                item.add_marker(pytest.mark.skip(reason=reason))
