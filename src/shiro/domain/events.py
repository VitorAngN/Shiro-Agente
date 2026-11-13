"""Eventos internos (``docs/03-arquitetura.md``, seção 9)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from shiro.domain.models import AgentResult, Channel, ExecutedCall


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    ts: datetime = Field(default_factory=_utcnow)


class TurnStarted(Event):
    session_id: str
    channel: Channel
    text: str


class TurnProgress(Event):
    """O que o turno está fazendo agora, para quem mostra uma barra de progresso.

    ``stage``: "thinking" (modelo pensando), "tool" (rodando uma ação),
    "confirming" (esperando sim ou não).
    """

    stage: str
    detail: str


class BackgroundNotice(Event):
    """Algo que aconteceu fora de um pedido (uma espera terminou, um vigia agiu)."""

    text: str


class ToolCallCompleted(Event):
    executed: ExecutedCall


class TurnFinished(Event):
    session_id: str
    channel: Channel
    text: str
    started_at: datetime
    result: AgentResult
