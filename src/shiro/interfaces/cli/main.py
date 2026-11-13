"""Linha de comando do SHIRO.

* ``shiro chat``: conversa por texto com o agente (marco 1a);
* ``shiro voice``: conversa por voz e utilitários de áudio (marco 1b, ``cli_voice``);
* ``shiro config``: ver e validar a configuração;
* ``shiro secrets``: chaves de API no cofre do sistema.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from shiro import __version__
from shiro.config import paths
from shiro.config.settings import ConfigError, Settings, load_settings
from shiro.domain.models import DecisionKind
from shiro.interfaces.cli.voice import add_voice_parser, run_voice


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

    secrets = commands.add_parser("secrets", help="chaves de API no cofre do Windows")
    secrets_commands = secrets.add_subparsers(dest="secrets_command", metavar="ação", required=True)
    secrets_set = secrets_commands.add_parser("set", help="guarda a chave de um provedor")
    secrets_set.add_argument("provider", choices=("gemini", "anthropic", "openai"))
    secrets_commands.add_parser("status", help="mostra quais chaves estão configuradas")
    secrets_delete = secrets_commands.add_parser("delete", help="apaga a chave de um provedor")
    secrets_delete.add_argument("provider", choices=("gemini", "anthropic", "openai"))

    chat = commands.add_parser("chat", help="conversa com a SHIRO por texto")
    chat.add_argument("-m", "--message", help="envia uma única mensagem e sai")
    chat.add_argument(
        "-v", "--verbose", action="store_true", help="mostra camada, modelo, tempo e ferramentas"
    )
    chat.add_argument(
        "--no-warmup", action="store_true", help="não pré-carrega o modelo local ao iniciar"
    )
    add_voice_parser(commands)

    commands.add_parser(
        "tray", help="a SHIRO na bandeja, com console (o modo sem console é shiro-tray)"
    )
    dashboard = commands.add_parser(
        "dashboard", help="abre o painel no navegador (só neste PC, em 127.0.0.1)"
    )
    dashboard.add_argument(
        "--no-browser", action="store_true", help="só mostra o link, sem abrir o navegador"
    )
    commands.add_parser("serve", help="roda o motor para o programa e o celular (ADR-0022)")
    commands.add_parser("setup", help="baixa e prepara os modelos (ouvido, voz e memória)")
    start = commands.add_parser("autostart", help="iniciar com o Windows (na bandeja)")
    start.add_argument("action", choices=("on", "off", "status"))
    return parser


async def _chat(settings: Settings, args: argparse.Namespace) -> int:
    # Importado aqui para "shiro --version" e "shiro config" não carregarem o agente.
    import sys

    from shiro.bootstrap.app import build_app
    from shiro.domain.ports import LLMError
    from shiro.infrastructure.observability.logging import (
        configure_logging,
        log_lifecycle,
        watch_event_loop,
    )
    from shiro.interfaces.text.session import (
        CliConfirmation,
        CliNotifier,
        TextSession,
        llm_down_message,
        use_safe_output,
    )
    from shiro.interfaces.text.theme import Theme

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=False)
    log_lifecycle("chat")
    watch_event_loop()
    theme = Theme.for_stream(sys.stdout)
    app = await build_app(
        settings, confirmation=CliConfirmation(theme=theme), notifier=CliNotifier(theme)
    )
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
        session.print(theme.status(app.cloud_llm is not None, app.cloud_status))
        if settings.policy.read_only_mode:
            session.print(theme.status(False, "modo somente leitura: ações pedem confirmação"))
        session.print("")
        app.start_background()
        if args.message:
            await session.send(args.message)
        else:
            await session.loop()
    finally:
        await app.aclose()
    return 0


async def _dashboard(settings: Settings, args: argparse.Namespace) -> int:
    import webbrowser

    from shiro.bootstrap.app import build_app
    from shiro.infrastructure.observability.logging import (
        configure_logging,
        log_lifecycle,
        watch_event_loop,
    )
    from shiro.interfaces.api.dashboard import Dashboard
    from shiro.interfaces.text.session import use_safe_output

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=False)
    log_lifecycle("dashboard")
    watch_event_loop()
    app = await build_app(settings, confirmation=_NoConfirmation())
    panel = Dashboard(app)
    try:
        try:
            url = await panel.open()
        except OSError:
            print(
                f"✗ A porta {settings.api.port} já está em uso. Se a SHIRO está na bandeja,"
                " use o menu dela: Abrir painel."
            )
            return 1
        print(f"Painel em {panel.base_url}")
        print("Link de entrada (uso único, vale só nesta execução):")
        print(f"  {url}")
        print("Os eventos ao vivo aparecem quando o painel roda junto da SHIRO (bandeja).")
        print("Ctrl+C para fechar.")
        if not args.no_browser:
            webbrowser.open(url)
        await asyncio.Event().wait()
    finally:
        await panel.close()
        await app.aclose()
    return 0


_crash_log: list[object] = []  # o arquivo precisa ficar aberto enquanto o motor roda


def _record_crashes(folder: Path) -> None:
    """Queda dura (biblioteca nativa de áudio, Whisper...) deixa a pilha em ``crash.log``."""
    import faulthandler

    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle = (folder / "crash.log").open("a", encoding="utf-8")
    except OSError:
        return
    handle.write(f"--- motor iniciado (pid {os.getpid()})\n")
    handle.flush()
    faulthandler.enable(handle)
    _crash_log.append(handle)
    # saída normal do Python deixa rastro; se o log terminar sem isto, o processo foi morto
    atexit.register(lambda: logging.getLogger("shiro").warning("motor saiu (atexit)"))


async def _serve(settings: Settings) -> int:
    from zoneinfo import ZoneInfo

    from shiro.application.devices.confirmations import RemoteConfirmations
    from shiro.application.devices.service import DeviceRegistry
    from shiro.bootstrap.app import build_app
    from shiro.infrastructure.observability.logging import (
        configure_logging,
        log_lifecycle,
        watch_event_loop,
    )
    from shiro.infrastructure.persistence.devices import SqliteDeviceStore
    from shiro.infrastructure.system.clock import SystemClock
    from shiro.interfaces.api.engine import (
        EngineServer,
        engine_api,
        ensure_local_token,
        write_launch_spec,
    )
    from shiro.interfaces.text.session import use_safe_output

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=sys.stderr is not None)
    log_lifecycle("serve")
    watch_event_loop()
    _record_crashes(paths.log_dir())
    from shiro.infrastructure.llm.ollama_service import OllamaService

    print(await OllamaService(settings.llm.local.base_url).ensure())
    confirmations = RemoteConfirmations()
    app = await build_app(settings, confirmation=confirmations, channel="api")
    try:
        registry = DeviceRegistry(
            SqliteDeviceStore(app.database), SystemClock(ZoneInfo(settings.general.timezone))
        )
        token = await ensure_local_token(registry, paths.data_dir())
        write_launch_spec(paths.data_dir())
        local = await registry.authenticate(token)
        api = engine_api(app, registry, confirmations, local_device_id=local.id if local else "")
        server = EngineServer(
            api,
            host=settings.devices.host,
            port=settings.devices.port,
        )
        try:
            await server.start()
        except OSError:
            print(f"✗ A porta {settings.devices.port} já está em uso: o motor já está rodando?")
            return 1
        print(f"Motor da SHIRO em http://{settings.devices.host}:{settings.devices.port}")
        for problem in app.problems:
            print(f"! {problem}")

        async def warm_up() -> None:  # modelo carregado antes do 1º pedido
            with contextlib.suppress(Exception):
                await app.agent.warm_up()

        warm = asyncio.create_task(warm_up())
        voice = api.state.voice
        if settings.voice.activation in ("wake_word", "both"):
            try:
                await voice.set_listening(True)
                print('Escutando o nome: diga "Shiro" e o pedido.')
            except Exception as exc:
                print(f"! não consegui ligar a escuta do nome: {exc}")
        print("Ctrl+C para encerrar.")
        try:
            await asyncio.Event().wait()
        except BaseException as exc:
            # sem terminal ninguém vê por que o motor parou: fica no log
            logging.getLogger("shiro").warning("serve encerrando: %r", exc)
            raise
        finally:
            warm.cancel()
            await voice.aclose()
            await server.stop()
    finally:
        await app.aclose()
    return 0


class _NoConfirmation:
    """O painel sozinho não roda turnos; se algo pedir confirmação, a resposta é não."""

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        return False


def _config_path() -> int:
    path = paths.config_file()
    state = "existe" if path.is_file() else "ainda não existe; os padrões serão usados"
    print(f"{path} ({state})")
    print(f"dados locais: {paths.data_dir()}")
    return 0


def _secrets(args: argparse.Namespace, prompt: Callable[[str], str] | None = None) -> int:
    import getpass

    from shiro.infrastructure.system import secrets

    if args.secrets_command == "status":
        for provider in secrets.PROVIDERS:
            source = secrets.key_source(provider)
            print(f"  {provider}: {'configurada (' + source + ')' if source else 'sem chave'}")
        return 0
    if args.secrets_command == "delete":
        try:
            removed = secrets.delete_api_key(args.provider)
        except secrets.SecretError as exc:
            print(f"✗ {exc}")
            return 1
        print("✓ chave apagada" if removed else "nenhuma chave guardada para esse provedor")
        return 0
    ask = prompt or getpass.getpass
    value = ask(f"Cole a chave de API do {args.provider} (não aparece na tela): ")
    try:
        secrets.set_api_key(args.provider, value)
    except (ValueError, secrets.SecretError) as exc:
        print(f"✗ {exc}")
        return 1
    print(f"✓ chave do {args.provider} guardada no cofre de credenciais do sistema")
    return 0


def _autostart(action: str) -> int:
    from shiro.infrastructure.system import autostart

    try:
        if action == "on":
            how = autostart.enable()
            detail = "Agendador de Tarefas" if how == "tarefa" else "registro do usuário (Run)"
            print(f"✓ a SHIRO vai iniciar na bandeja depois do logon ({detail})")
        elif action == "off":
            removed = autostart.disable()
            print("✓ início automático desligado" if removed else "já estava desligado")
        else:
            how = autostart.status()
            print(f"início com o Windows: {how or 'desligado'}")
            print(f"comando: {autostart.launcher().command_line}")
    except autostart.AutostartError as exc:
        print(f"✗ {exc}")
        return 1
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
    from shiro.infrastructure.system.secrets import key_source

    source = key_source(cloud.provider)
    key = f"chave no {source}" if source else "sem chave"
    print(
        f"  nuvem: {cloud.provider}/{cloud.model}, {key} "
        f"(até {cloud.daily_request_limit} pedidos/dia, US$ {cloud.daily_budget_usd:.2f})"
    )
    print(f"  ativação por voz: {settings.voice.activation}")
    print(f"  modo somente leitura: {'sim' if settings.policy.read_only_mode else 'não'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada do comando ``shiro``."""
    args = _build_parser().parse_args(argv)
    if args.command == "secrets":
        return _secrets(args)
    if args.command == "config":
        if args.config_command == "path":
            return _config_path()
        return _config_check(args.file)
    if args.command == "autostart":
        return _autostart(args.action)
    if args.command == "tray":
        from shiro.interfaces.tray.main import main as tray_main

        return tray_main()
    if args.command in ("chat", "voice", "setup", "dashboard", "serve"):
        try:
            settings = load_settings()
        except ConfigError as exc:
            print(f"✗ {exc}")
            return 1
        if args.command == "setup":
            args.voice_command = "setup"
            return run_voice(settings, args)
        if args.command == "voice":
            return run_voice(settings, args)
        try:
            if args.command == "serve":
                return asyncio.run(_serve(settings))
            if args.command == "dashboard":
                return asyncio.run(_dashboard(settings, args))
            return asyncio.run(_chat(settings, args))
        except KeyboardInterrupt:
            return 130
    print(f"shiro {__version__}: Fase 1 (MVP de voz).")
    print("Use 'shiro chat' (texto), 'shiro voice' (voz), 'shiro config check' ou 'shiro --help'.")
    return 0
