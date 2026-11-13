"""Montagem das habilidades (ADR-0025): o que pode virar passo e como cada passo é dito."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from shiro.application.registry import ToolRegistry
from shiro.domain.models import RiskLevel

# Não viram passo: criar ou esquecer habilidades e lições (uma habilidade não cria outra).
_NOT_STEPS = frozenset({"skills", "learning"})


def _usable(registry: ToolRegistry, name: str) -> bool:
    tool = registry.get(name)
    return (
        tool is not None
        and tool.spec.group not in _NOT_STEPS
        and tool.spec.risk is not RiskLevel.R4
    )


def step_check(registry: ToolRegistry) -> Any:
    def check(tool_name: str, args: dict[str, Any]) -> str | None:
        tool = registry.get(tool_name)
        if tool is None or not _usable(registry, tool_name):
            return "não conheço essa ação (use só as ferramentas da lista)"
        try:
            tool.spec.args_model.model_validate(args)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "argumentos"
            return f"{where}: {first['msg']}"
        return None

    return check


def step_words(registry: ToolRegistry) -> Any:
    def words(tool_name: str, args: dict[str, Any]) -> str:
        tool = registry.get(tool_name)
        if tool is None:
            return tool_name
        try:
            return tool.describe(tool.spec.args_model.model_validate(args))
        except Exception:  # só para mostrar: um passo com {x} pode não validar ainda
            return f"{tool_name} {args}"

    return words


def step_catalog(registry: ToolRegistry) -> str:
    """Lista curta para o modelo: nome(argumentos) de cada ação que pode virar passo."""
    parts: list[str] = []
    for name in registry.names():
        tool = registry.get(name)
        if tool is None or not _usable(registry, name):
            continue
        fields = ",".join(tool.spec.args_model.model_fields)
        parts.append(f"{name}({fields})")
    return "; ".join(parts)
