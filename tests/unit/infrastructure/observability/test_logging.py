"""Logs em JSON, sem segredos."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import structlog

from shiro.config.settings import LoggingSettings
from shiro.infrastructure.observability.logging import (
    LOG_FILE_NAME,
    REDACTED,
    configure_logging,
    redact_secrets,
)


def _flush() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_writes_json_lines_with_timestamp_and_level(tmp_path: Path) -> None:
    configure_logging(LoggingSettings(), tmp_path, console=False)

    structlog.get_logger("teste").info("turno_concluido", latency_ms=420)
    _flush()

    line = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "turno_concluido"
    assert record["level"] == "info"
    assert record["latency_ms"] == 420
    assert "timestamp" in record


def test_secrets_never_reach_the_file(tmp_path: Path) -> None:
    configure_logging(LoggingSettings(), tmp_path, console=False)

    structlog.get_logger("teste").info(
        "provedor_configurado", api_key="sk-segredo", provider="gemini"
    )
    _flush()

    content = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "sk-segredo" not in content
    assert REDACTED in content
    assert "gemini" in content


def test_level_filters_lower_messages(tmp_path: Path) -> None:
    configure_logging(LoggingSettings(level="WARNING"), tmp_path, console=False)

    log = structlog.get_logger("teste")
    log.info("nao_deve_aparecer")
    log.warning("deve_aparecer")
    _flush()

    content = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "nao_deve_aparecer" not in content
    assert "deve_aparecer" in content


def test_redact_secrets_matches_common_key_names() -> None:
    event = {"Authorization": "Bearer x", "refresh_token": "y", "password": "z", "user": "ok"}

    result = redact_secrets(None, "info", event)

    assert result == {
        "Authorization": REDACTED,
        "refresh_token": REDACTED,
        "password": REDACTED,
        "user": "ok",
    }
