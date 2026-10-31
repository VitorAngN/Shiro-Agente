"""Linha de comando do SHIRO.

* ``shiro chat``: conversa por texto com o agente (marco 1a);
* ``shiro config``: ver e validar a configuração.

A voz chega no marco 1b (ver ``docs/06-roadmap.md``).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from shiro import __version__, paths
from shiro.settings import ConfigError, Settings, load_settings


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

    chat = commands.add_parser("chat", help="conversa com o SHIRO por texto")
    chat.add_argument("-m", "--message", help="envia uma única mensagem e sai")
    chat.add_argument(
        "-v", "--verbose", action="store_true", help="mostra camada, modelo, tempo e ferramentas"
    )
    chat.add_argument(
        "--no-warmup", action="store_true", help="não pré-carrega o modelo local ao iniciar"
    )
    return parser


async def _chat(settings: Settings, args: argparse.Namespace) -> int:
    # Importado aqui para "shiro --version" e "shiro config" não carregarem o agente.
    import sys

    from shiro.app import build_app
    from shiro.core.ports import LLMError
    from shiro.interfaces.text import (
        CliConfirmation,
        TextSession,
        llm_down_message,
        use_safe_output,
    )
    from shiro.interfaces.theme import Theme
    from shiro.observability.logging import configure_logging

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=False)
    theme = Theme.for_stream(sys.stdout)
    app = await build_app(settings, confirmation=CliConfirmation(theme=theme))
    session = TextSession(
        app.agent.run_turn,
        name=settings.general.assistant_name,
        verbose=args.verbose,
        theme=theme,
    )
    try:
        session.print(theme.banner(__version__))
        model = settings.llm.local.model
        if args.no_warmup:
            session.print(theme.status(True, f"{model}: aquecimento pulado"))
        else:
            try:
                await app.agent.warm_up()
                session.print(theme.status(True, f"{model} carregado"))
            except LLMError as exc:
                session.print(
                    theme.status(False, llm_down_message(settings.llm.local.base_url, exc))
                )
        broken = await app.audit.verify()
        if broken is None:
            session.print(theme.status(True, "auditoria íntegra"))
        else:
            session.print(theme.status(False, f"auditoria: evento {broken} foi alterado"))
        if settings.policy.read_only_mode:
            session.print(theme.status(False, "modo somente leitura: ações pedem confirmação"))
        session.print("")
        if args.message:
            await session.send(args.message)
        else:
            await session.loop()
    finally:
        await app.aclose()
    return 0


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
    if args.command == "chat":
        try:
            settings = load_settings()
        except ConfigError as exc:
            print(f"✗ {exc}")
            return 1
        try:
            return asyncio.run(_chat(settings, args))
        except KeyboardInterrupt:
            return 130
    print(f"shiro {__version__}: Fase 1 (MVP de voz), marco 1a: agente por texto.")
    print("Use 'shiro chat' para conversar, 'shiro config check' ou 'shiro --help'.")
    return 0
