"""Portas do núcleo: as interfaces que os adaptadores implementam (ADR-0002).

O núcleo depende só destes ``Protocol``s. Implementações concretas (Ollama,
SQLite, Windows) são ligadas em ``shiro.app``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shiro.domain.models import (
    CompletionRequest,
    CompletionResponse,
    Decision,
    DecisionKind,
    RiskLevel,
    ToolDefinition,
    ToolResult,
)


class LLMError(Exception):
    """O provedor de LLM falhou (rede, servidor fora do ar, resposta inválida)."""


class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Gera a próxima mensagem. Levanta ``LLMError`` em caso de falha."""
        ...

    async def warm_up(self, request: CompletionRequest) -> None:
        """Carrega o modelo e o prefixo do pedido no cache (ADR-0011)."""
        ...


class ToolSpec(BaseModel):
    """Declaração de uma ferramenta: nome, argumentos e risco (ADR-0005)."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    args_model: type[BaseModel]
    risk: RiskLevel
    timeout_s: float = Field(default=10.0, gt=0)
    output_trusted: bool = True
    local_only: bool = False
    confirm: bool = False
    """Sempre pede confirmação, mesmo fora do modo somente leitura (ex.: organizar uma pasta)."""
    external: bool = False
    """Manda dados para fora do PC (ex.: pesquisa na web)."""
    group: str = "core"
    """Grupo de assunto: fora de "core", só aparece para o modelo quando o pedido é do assunto."""
    parameters: dict[str, Any] | None = None
    """Schema enviado ao modelo; quando ``None``, é gerado a partir de ``args_model``."""


class ToolContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    now: datetime
    utterance: str = ""
    """O pedido do usuário neste turno, para ancorar argumentos (ADR-0014)."""


class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    def describe(self, args: BaseModel) -> str:
        """Frase curta usada na confirmação, ex.: "definir o volume em 20%"."""
        ...

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


class ToolCatalog(Protocol):
    def get(self, name: str) -> Tool | None: ...

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Definições em ordem estável, para o cache de prefixo funcionar."""
        ...

    def definitions_for(
        self, text: str, extra_groups: Set[str] = frozenset()
    ) -> tuple[ToolDefinition, ...]:
        """Só as ferramentas do núcleo e dos grupos do assunto do pedido (ADR-0018)."""
        ...

    def group_of(self, name: str) -> str | None: ...


class PolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tainted: bool = False
    batch_size: int = Field(default=1, ge=1)
    always_confirm: bool = False
    external: bool = False
    private_context: bool = False
    """O turno tem dados pessoais (memórias, arquivos): mandar algo para fora pede confirmação."""


class MemoryRecall(Protocol):
    """Memórias que ajudam a responder um pedido (RF-42). Sempre ``local_only``."""

    async def relevant(self, text: str) -> Sequence[str]: ...


class Policy(Protocol):
    def evaluate(self, risk: RiskLevel, ctx: PolicyContext) -> Decision: ...


class ConfirmationChannel(Protocol):
    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        """Pergunta ao usuário; ``True`` significa aprovado."""
        ...


class AuditSink(Protocol):
    async def record(self, event_type: str, trace_id: str, payload: Mapping[str, Any]) -> None: ...


class UsageLedger(Protocol):
    """Uso diário dos provedores de nuvem (tabela ``provider_usage``)."""

    async def today(self, provider: str) -> tuple[int, float]:
        """(requisições, custo estimado em US$) do provedor hoje."""
        ...

    async def add(
        self, provider: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float
    ) -> None: ...


class Notifier(Protocol):
    """Avisos que a SHIRO dá por iniciativa própria (prazos, lembretes)."""

    async def notify(self, title: str, message: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """Data e hora atuais, sempre com fuso."""
        ...
