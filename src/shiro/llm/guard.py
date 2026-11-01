"""Proteções da nuvem: limite por minuto, teto diário e cadeia de fallback (ADR-0003).

Nada aqui espera: se um limite foi atingido, a chamada falha na hora com
``LLMError`` e o agente volta para o modelo local. Para voz, responder rápido
com o modelo local é melhor do que esperar a janela do limite abrir.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from shiro.core.models import CompletionRequest, CompletionResponse
from shiro.core.ports import LLMError, LLMProvider, UsageLedger

log = logging.getLogger(__name__)


class CloudLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rpm_limit: int = Field(default=5, ge=1)
    daily_request_limit: int = Field(default=200, ge=1)
    daily_budget_usd: float = Field(default=0.5, ge=0)
    price_input_per_mtok: float = Field(default=0.0, ge=0)
    price_output_per_mtok: float = Field(default=0.0, ge=0)

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (
            tokens_in * self.price_input_per_mtok + tokens_out * self.price_output_per_mtok
        ) / 1_000_000


class GuardedProvider:
    """Envolve um provedor de nuvem com limites e registro de uso."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        limits: CloudLimits,
        ledger: UsageLedger,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._limits = limits
        self._ledger = ledger
        self._clock = clock
        self._recent: deque[float] = deque()

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def model(self) -> str:
        return self._inner.model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        await self.reserve()
        response = await self._inner.complete(request)
        await self.record(response.usage.prompt_tokens, response.usage.completion_tokens)
        return response

    async def reserve(self) -> None:
        """Confere limites e conta mais um pedido (também usado pela pesquisa na web)."""
        await self._check()
        self._recent.append(self._clock())

    async def record(self, tokens_in: int, tokens_out: int) -> None:
        await self._ledger.add(
            self.name, self.model, tokens_in, tokens_out, self._limits.cost(tokens_in, tokens_out)
        )

    async def warm_up(self, request: CompletionRequest) -> None:
        await self._inner.warm_up(request)

    async def _check(self) -> None:
        now = self._clock()
        while self._recent and now - self._recent[0] >= 60:
            self._recent.popleft()
        if len(self._recent) >= self._limits.rpm_limit:
            msg = f"{self.name}: limite de {self._limits.rpm_limit} requisições por minuto"
            raise LLMError(msg)
        requests, cost = await self._ledger.today(self.name)
        if requests >= self._limits.daily_request_limit:
            msg = f"{self.name}: limite diário de {self._limits.daily_request_limit} requisições"
            raise LLMError(msg)
        if self._limits.daily_budget_usd and cost >= self._limits.daily_budget_usd:
            msg = f"{self.name}: orçamento diário de US$ {self._limits.daily_budget_usd} atingido"
            raise LLMError(msg)


class FallbackProvider:
    """Tenta cada provedor em ordem até um responder."""

    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        if not providers:
            msg = "a cadeia de fallback precisa de ao menos um provedor"
            raise ValueError(msg)
        self._providers = tuple(providers)
        self._last = self._providers[0]

    @property
    def name(self) -> str:
        return self._last.name

    @property
    def model(self) -> str:
        return self._last.model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        errors: list[str] = []
        for provider in self._providers:
            try:
                response = await provider.complete(request)
            except LLMError as exc:
                log.warning("provedor %s falhou: %s", provider.name, exc)
                errors.append(str(exc))
                continue
            self._last = provider
            return response
        raise LLMError("; ".join(errors))

    async def warm_up(self, request: CompletionRequest) -> None:
        await self._providers[0].warm_up(request)
