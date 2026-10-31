"""Registro de ferramentas (implementa a porta ``ToolCatalog``)."""

from __future__ import annotations

from typing import Any

from shiro.core.models import ToolDefinition
from shiro.core.ports import Tool, ToolSpec


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove ``title`` e chaves vazias: menos tokens no pedido do modelo local."""

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: clean(value)
                for key, value in node.items()  # pyright: ignore[reportUnknownVariableType]
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
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._definitions: tuple[ToolDefinition, ...] | None = None

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            msg = f"ferramenta registrada duas vezes: {name}"
            raise ValueError(msg)
        self._tools[name] = tool
        self._definitions = None

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
