"""Linha de comando do SHIRO.

Fase 0: só utilitários de diagnóstico. O assistente em si chega na Fase 1
(ver ``docs/06-roadmap.md``).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from shiro import __version__, paths
from shiro.settings import ConfigError, load_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shiro",
        description="SHIRO: assistente pessoal com IA para Windows.",
    )
    parser.add_argument("--version", action="version", version=f"shiro {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="comando")

    config = commands.add_parser("config", help="ver e validar a configuração")
    config_commands = config.add_subparsers(dest="config_command", metavar="ação", required=True)
    config_commands.add_parser("path", help="mostra onde fica o shiro.toml")
    check = config_commands.add_parser("check", help="valida o shiro.toml")
    check.add_argument("--file", type=Path, help="valida outro arquivo em vez do padrão")
    return parser


def _config_path() -> int:
    path = paths.config_file()
    state = "existe" if path.is_file() else "ainda não existe; os padrões serão usados"
    print(f"{path} ({state})")
    print(f"dados locais: {paths.data_dir()}")
    return 0


def _config_check(file: Path | None) -> int:
    try:
        settings = load_settings(file)
    except ConfigError as exc:
        print(f"✗ {exc}")
        return 1
    print("✓ configuração válida")
    print(f"  modelo local: {settings.llm.local.model}")
    cloud = settings.llm.cloud
    print(f"  nuvem: {cloud.provider} (orçamento diário US$ {cloud.daily_budget_usd:.2f})")
    print(f"  ativação por voz: {settings.voice.activation}")
    print(f"  modo somente leitura: {'sim' if settings.policy.read_only_mode else 'não'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada do comando ``shiro``."""
    args = _build_parser().parse_args(argv)
    if args.command == "config":
        if args.config_command == "path":
            return _config_path()
        return _config_check(args.file)
    print(f"shiro {__version__}: Fase 0 (fundação). O assistente chega na Fase 1.")
    print("Use 'shiro config check' para validar a configuração ou 'shiro --help'.")
    return 0
