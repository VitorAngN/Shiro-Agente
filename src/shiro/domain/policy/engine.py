"""Motor de políticas: decide se uma chamada de ferramenta pode rodar (ADR-0005).

É uma função pura, testada por tabela. As regras são aplicadas em ordem, e a
primeira que decidir encerra a avaliação (``docs/05-seguranca.md``, seção 2).

As listas de apps e pastas permitidas são aplicadas na validação dos
argumentos de cada ferramenta: um app fora da lista nem chega a ser um
argumento válido.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shiro.domain.models import Decision, DecisionKind, RiskLevel
from shiro.domain.ports import PolicyContext


class PolicyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    read_only_mode: bool = True
    batch_confirm_threshold: int = Field(default=5, ge=1)


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self._config = config

    @property
    def config(self) -> PolicyConfig:
        return self._config

    def evaluate(self, risk: RiskLevel, ctx: PolicyContext) -> Decision:
        if risk is RiskLevel.R4:
            return Decision(kind=DecisionKind.DENY, reason="ação proibida (R4)")
        if risk is RiskLevel.R3:
            return Decision(
                kind=DecisionKind.CONFIRM_PHYSICAL, reason="ação irreversível ou de alto impacto"
            )
        if ctx.tainted and risk.rank >= 2:
            return Decision(
                kind=DecisionKind.CONFIRM_VOICE,
                reason="o contexto contém conteúdo externo não confiável",
            )
        if risk is RiskLevel.R2 and ctx.batch_size > self._config.batch_confirm_threshold:
            return Decision(
                kind=DecisionKind.CONFIRM_VOICE, reason=f"ação em lote ({ctx.batch_size} itens)"
            )
        if ctx.external and ctx.private_context:
            return Decision(
                kind=DecisionKind.CONFIRM_VOICE,
                reason="vai mandar para a internet algo de um pedido com dados pessoais",
            )
        if ctx.always_confirm and risk.rank >= 1:
            return Decision(kind=DecisionKind.CONFIRM_VOICE, reason="ação que sempre confirma")
        if self._config.read_only_mode and risk.rank >= 1:
            return Decision(kind=DecisionKind.CONFIRM_VOICE, reason="modo somente leitura ativo")
        return Decision(kind=DecisionKind.ALLOW, reason="permitido")
