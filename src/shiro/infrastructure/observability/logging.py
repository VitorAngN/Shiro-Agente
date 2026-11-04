"""Logging estruturado.

* Arquivo: JSON por linha, com rotação por tamanho, em ``<dados>/logs/shiro.log``.
* Console: formato legível para desenvolvimento.
* Valores de chaves sensíveis (``api_key``, ``token``, ``password``...) são mascarados
  antes de chegar a qualquer saída (ameaça A-06 em ``docs/05-seguranca.md``).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

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
