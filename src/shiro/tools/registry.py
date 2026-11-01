"""Registro de ferramentas (implementa a porta ``ToolCatalog``)."""

from __future__ import annotations

import re
from collections.abc import Set
from typing import Any

from shiro.core.models import ToolDefinition
from shiro.core.ports import Tool, ToolSpec
from shiro.core.text import normalize


def _without_null(node: dict[str, Any]) -> dict[str, Any]:
    """``anyOf: [X, null]`` com ``default: null`` vira só ``X``: modelos pequenos erram menos.

    O campo continua opcional porque fica fora de ``required``.
    """
    options = node.get("anyOf")
    if not isinstance(options, list) or node.get("default", ...) is not None:
        return node
    real = [o for o in options if o != {"type": "null"}]  # pyright: ignore[reportUnknownVariableType]
    if len(real) != 1 or len(real) == len(options):  # pyright: ignore[reportUnknownArgumentType]
        return node
    simplified = {k: v for k, v in node.items() if k not in ("anyOf", "default")}
    simplified.update(real[0])  # pyright: ignore[reportUnknownArgumentType]
    return simplified


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove ``title``, nulos opcionais e chaves vazias: menos tokens e menos confusão."""

    def clean(node: Any, *, is_properties: bool = False) -> Any:
        if isinstance(node, dict):
            if is_properties:
                # Aqui as chaves são nomes de campos: um campo pode se chamar "title".
                return {key: clean(value) for key, value in node.items()}  # pyright: ignore[reportUnknownVariableType]
            node = _without_null(node)  # pyright: ignore[reportUnknownArgumentType]
            return {
                key: clean(value, is_properties=key == "properties")
                for key, value in node.items()
                if key != "title"
            }
        if isinstance(node, list):
            return [clean(item) for item in node]  # pyright: ignore[reportUnknownVariableType]
        return node

    cleaned: dict[str, Any] = clean(schema)
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    if not cleaned.get("required"):
        cleaned.pop("required", None)
    return cleaned


def definition_for(spec: ToolSpec) -> ToolDefinition:
    parameters = spec.parameters or compact_schema(spec.args_model.model_json_schema())
    return ToolDefinition(name=spec.name, description=spec.description, parameters=parameters)


class ToolRegistry:
    """Ferramentas registradas, com seleção por assunto (ADR-0018).

    O modelo local de 4B erra mais com muitas ferramentas no pedido. Ferramentas
    do grupo "core" vão sempre; as dos outros grupos (memória, arquivos, web) só
    quando o pedido fala do assunto (``gate``) ou quando o grupo foi usado há pouco.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._definitions: tuple[ToolDefinition, ...] | None = None
        self._gates: dict[str, re.Pattern[str]] = {}
        self._by_groups: dict[frozenset[str], tuple[ToolDefinition, ...]] = {}

    def gate(self, group: str, pattern: str) -> None:
        """Palavras (regex sobre o texto normalizado) que trazem o grupo para o pedido."""
        self._gates[group] = re.compile(pattern)
        self._by_groups.clear()

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            msg = f"ferramenta registrada duas vezes: {name}"
            raise ValueError(msg)
        self._tools[name] = tool
        self._definitions = None
        self._by_groups.clear()

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def definitions(self) -> tuple[ToolDefinition, ...]:
        if self._definitions is None:
            self._definitions = tuple(
                definition_for(self._tools[name].spec) for name in sorted(self._tools)
            )
        return self._definitions

    def group_of(self, name: str) -> str | None:
        tool = self._tools.get(name)
        return tool.spec.group if tool is not None else None

    def groups_for(self, text: str) -> frozenset[str]:
        plain = normalize(text)
        return frozenset(g for g, pattern in self._gates.items() if pattern.search(plain))

    def definitions_for(
        self, text: str, extra_groups: Set[str] = frozenset()
    ) -> tuple[ToolDefinition, ...]:
        groups = frozenset({"core"}) | self.groups_for(text) | frozenset(extra_groups)
        # Grupo sem palavra-chave cadastrada vai sempre (compatível com ferramentas antigas).
        groups |= frozenset(
            t.spec.group for t in self._tools.values() if t.spec.group not in self._gates
        )
        cached = self._by_groups.get(groups)
        if cached is None:
            cached = tuple(
                d for d in self.definitions() if self._tools[d.name].spec.group in groups
            )
            self._by_groups[groups] = cached
        return cached
