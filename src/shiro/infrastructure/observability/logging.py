"""Logging estruturado.

* Arquivo: JSON por linha, com rotação por tamanho, em ``<dados>/logs/shiro.log``.
* Console: formato legível para desenvolvimento.
* Valores de chaves sensíveis (``api_key``, ``token``, ``password``...) são mascarados
  antes de chegar a qualquer saída (ameaça A-06 em ``docs/05-seguranca.md``).
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
import threading
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from shiro import __version__
from shiro.config.settings import LoggingSettings

LOG_FILE_NAME = "shiro.log"
REDACTED = "***"
_SENSITIVE_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "authorization")


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Processador do structlog que mascara valores de chaves sensíveis."""
    for key in event_dict:
        if any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(
    settings: LoggingSettings, log_dir: Path | None, *, console: bool = True
) -> None:
    """Configura o structlog sobre o logging da biblioteca padrão.

    Args:
        settings: nível e rotação.
        log_dir: pasta do arquivo de log; ``None`` desativa o arquivo.
        console: se também deve escrever no stderr.
    """
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_secrets,
    ]

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(settings.level)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / LOG_FILE_NAME,
            maxBytes=settings.max_file_mb * 1024 * 1024,
            backupCount=settings.backups,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(ensure_ascii=False),
                ],
                foreign_pre_chain=shared,
            )
        )
        root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
                ],
                foreign_pre_chain=shared,
            )
        )
        root.addHandler(console_handler)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def log_lifecycle(command: str) -> None:
    """Registra início, fim e erros não tratados (do processo, de threads e do asyncio).

    Sem isso, um processo que morre ou trava não deixa rastro no log.
    """
    log = logging.getLogger("shiro")
    log.info("SHIRO %s iniciando (pid %d, versão %s)", command, os.getpid(), __version__)
    previous = sys.excepthook

    def on_crash(kind: type[BaseException], value: BaseException, tb: Any) -> None:
        log.critical("erro não tratado em %s", command, exc_info=(kind, value, tb))
        previous(kind, value, tb)

    def on_thread_crash(args: threading.ExceptHookArgs) -> None:
        name = args.thread.name if args.thread is not None else "?"
        log.critical(
            "erro não tratado na thread %s",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # type: ignore[arg-type]
        )

    sys.excepthook = on_crash
    threading.excepthook = on_thread_crash
    atexit.register(log.info, "SHIRO %s encerrando (pid %d)", command, os.getpid())


def watch_event_loop() -> None:
    """Erros de tarefas do asyncio que ninguém aguardou vão para o log."""
    log = logging.getLogger("shiro")

    def handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        log.error(
            "erro no laço do asyncio: %s", context.get("message"), exc_info=context.get("exception")
        )

    asyncio.get_running_loop().set_exception_handler(handler)
