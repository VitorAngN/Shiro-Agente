"""Barramento de eventos assíncrono e tipado (ADR-0002)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from shiro.domain.events import Event

log = logging.getLogger(__name__)

type Handler[E: Event] = Callable[[E], Awaitable[None]]


class EventBus:
    """Pub/sub em processo.

    Os handlers rodam em sequência, na ordem de inscrição. A falha de um
    handler é registrada no log e não impede os demais nem quem publicou.
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[type[Event], Handler[Any]]] = []

    def subscribe[E: Event](self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers.append((event_type, cast("Handler[Any]", handler)))

    async def publish(self, event: Event) -> None:
        for event_type, handler in self._handlers:
            if not isinstance(event, event_type):
                continue
            try:
                await handler(event)
            except Exception:
                log.exception("handler de evento falhou: %s", type(event).__name__)
