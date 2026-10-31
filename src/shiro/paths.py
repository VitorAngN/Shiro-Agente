"""Onde o SHIRO guarda configuração e dados.

Nada disso fica dentro da pasta do projeto, para que dados pessoais nunca
acabem no repositório (ver ``docs/05-seguranca.md``, seção 6).

| Plataforma | Configuração                  | Dados                          |
|------------|-------------------------------|--------------------------------|
| Windows    | ``%APPDATA%\\SHIRO``          | ``%LOCALAPPDATA%\\SHIRO``      |
| Outras     | ``$XDG_CONFIG_HOME/shiro``    | ``$XDG_DATA_HOME/shiro``       |

As variáveis ``SHIRO_CONFIG`` (arquivo) e ``SHIRO_DATA_DIR`` (pasta) têm prioridade,
o que facilita testes e instalações portáteis.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

CONFIG_FILE_NAME = "shiro.toml"


def _is_windows(platform: str | None) -> bool:
    return (platform or sys.platform) == "win32"


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def config_dir(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Pasta da configuração do usuário."""
    values = _env(env)
    if _is_windows(platform):
        base = values.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "SHIRO"
    base = values.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "shiro"


def config_file(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Arquivo ``shiro.toml`` em uso."""
    override = _env(env).get("SHIRO_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir(env=env, platform=platform) / CONFIG_FILE_NAME


def data_dir(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Pasta de dados locais: banco, logs, lixeira e modelos de voz."""
    values = _env(env)
    override = values.get("SHIRO_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if _is_windows(platform):
        base = values.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "SHIRO"
    base = values.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "shiro"


def log_dir(*, env: Mapping[str, str] | None = None, platform: str | None = None) -> Path:
    """Pasta dos arquivos de log."""
    return data_dir(env=env, platform=platform) / "logs"
