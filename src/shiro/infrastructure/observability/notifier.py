"""Notificações que só vão para o log (quando não há bandeja nem voz)."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class LogNotifier:
    """Avisos só no log; as interfaces (texto, voz, bandeja) trazem o seu."""

    async def notify(self, title: str, message: str) -> None:
        log.info("aviso: %s", message)
