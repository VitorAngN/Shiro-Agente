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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = REPO_ROOT / "config" / "shiro.example.toml"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for key in list(os.environ):
        if key.startswith("SHIRO_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SHIRO_CONFIG", str(tmp_path / "config" / "shiro.toml"))
    monkeypatch.setenv("SHIRO_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path


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
