"""Registro de ferramentas (implementa a porta ``ToolCatalog``)."""

from __future__ import annotations

from typing import Any

from shiro.core.models import ToolDefinition
from shiro.core.ports import Tool, ToolSpec


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
