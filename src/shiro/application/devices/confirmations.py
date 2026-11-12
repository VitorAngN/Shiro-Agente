"""Confirmação por outro aparelho (ADR-0022): a pergunta fica pendente até o cliente responder.

O turno do agente espera aqui; o programa (ou o celular) busca as perguntas
pendentes e responde sim ou não. Sem resposta no prazo, vale não.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from shiro.domain.ids import uuid7
from shiro.domain.models import DecisionKind


@dataclass(frozen=True)
class Pending:
    id: str
    prompt: str
    kind: DecisionKind


class RemoteConfirmations:
    """Implementa ``ConfirmationChannel`` para pedidos que chegam pela API."""

    def __init__(self, timeout_s: float = 60.0) -> None:
        self._timeout_s = timeout_s
        self._waiting: dict[str, tuple[Pending, asyncio.Future[bool]]] = {}

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        pending = Pending(uuid7(), prompt, kind)
        answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiting[pending.id] = (pending, answer)
        try:
            with contextlib.suppress(TimeoutError):
                return await asyncio.wait_for(answer, self._timeout_s)
            return False
        finally:
            self._waiting.pop(pending.id, None)

    def pending(self) -> list[Pending]:
        return [pending for pending, _ in self._waiting.values()]

    def answer(self, pending_id: str, approve: bool) -> bool:
        """``True`` se havia essa pergunta esperando resposta."""
        found = self._waiting.get(pending_id)
        if found is None or found[1].done():
            return False
        found[1].set_result(approve)
        return True
