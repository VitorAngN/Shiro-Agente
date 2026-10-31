"""Entidades e value objects do núcleo.

Tudo aqui é imutável e independente de provedor: cada adaptador de LLM converte
de e para estes formatos (ADR-0003).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RiskLevel(StrEnum):
    """Nível de risco de uma ferramenta (``docs/05-seguranca.md``)."""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"

    @property
    def rank(self) -> int:
        return int(self.value[1])


class Tier(StrEnum):
    """Camada que respondeu ao pedido (ADR-0003)."""

    T0 = "T0"
    T1 = "T1"
    T2 = "T2"


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


Channel = Literal["text", "voice", "api", "scheduler"]


class ToolCall(_Frozen):
    """Pedido do modelo (ou do Tier 0) para executar uma ferramenta."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict[str, Any])


class Message(_Frozen):
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None


class ToolDefinition(_Frozen):
    """O que o modelo enxerga de uma ferramenta."""

    name: str
    description: str
    parameters: dict[str, Any]


class CompletionRequest(_Frozen):
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()


class Usage(_Frozen):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class CompletionResponse(_Frozen):
    provider: str
    model: str
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    latency_ms: int = 0


class ToolResult(_Frozen):
    """Resultado de uma ferramenta.

    ``content`` volta para o modelo; ``say`` é a frase curta usada quando o
    pedido é resolvido no Tier 0, sem passar pelo modelo.
    """

    ok: bool
    content: str
    say: str | None = None

    @classmethod
    def success(cls, content: str, *, say: str | None = None) -> ToolResult:
        return cls(ok=True, content=content, say=say)

    @classmethod
    def failure(cls, content: str) -> ToolResult:
        return cls(ok=False, content=content, say=content)


class DecisionKind(StrEnum):
    ALLOW = "allow"
    CONFIRM_VOICE = "confirm_voice"
    CONFIRM_PHYSICAL = "confirm_physical"
    DENY = "deny"


class Decision(_Frozen):
    kind: DecisionKind
    reason: str

    @property
    def needs_confirmation(self) -> bool:
        return self.kind in {DecisionKind.CONFIRM_VOICE, DecisionKind.CONFIRM_PHYSICAL}

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW


class CallOutcome(StrEnum):
    """Como terminou uma chamada de ferramenta (coluna ``tool_call.decision``)."""

    ALLOWED = "allow"
    CONFIRMED = "confirmed"
    DENIED = "denied"
    BLOCKED = "blocked"


class ExecutedCall(_Frozen):
    call: ToolCall
    risk: RiskLevel | None
    outcome: CallOutcome
    reason: str
    result: ToolResult
    duration_ms: int = 0

    @property
    def had_effect(self) -> bool:
        """Uma ferramenta com efeito (R1+) rodou e deu certo."""
        return (
            self.risk is not None
            and self.risk.rank >= 1
            and self.outcome in {CallOutcome.ALLOWED, CallOutcome.CONFIRMED}
            and self.result.ok
        )


class AgentResult(_Frozen):
    text: str
    tier: Tier
    provider: str | None = None
    model: str | None = None
    calls: tuple[ExecutedCall, ...] = ()
    steps: int = 0
    latency_ms: int = 0
    usage: Usage = Usage()
    claim_blocked: bool = False
