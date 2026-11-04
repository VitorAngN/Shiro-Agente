"""Registro de ferramentas: definições ordenadas, únicas e esquemas compactos."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from shiro.application.registry import ToolRegistry, compact_schema
from shiro.domain.models import RiskLevel
from tests.fakes.agent import FakeTool


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["play", "pause"] = Field(description="Ação")
    level: int = Field(default=10, ge=0, le=100)


def test_compact_schema_drops_titles() -> None:
    schema = compact_schema(_Args.model_json_schema())
    assert "title" not in schema
    assert "title" not in schema["properties"]["action"]
    assert schema["properties"]["action"]["enum"] == ["play", "pause"]
    assert schema["required"] == ["action"]


def test_registry_definitions_are_sorted_and_unique() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("zeta"))
    registry.register(FakeTool("alpha", risk=RiskLevel.R0))

    assert [d.name for d in registry.definitions()] == ["alpha", "zeta"]
    assert registry.get("alpha") is not None
    assert registry.get("nope") is None
    with pytest.raises(ValueError, match="duas vezes"):
        registry.register(FakeTool("alpha"))


class _Titled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(description="Título da atividade")
    due_text: str | None = Field(default=None, description="Prazo")


def test_compact_schema_keeps_fields_named_title_and_simplifies_optionals() -> None:
    """Regressão: o campo "title" sumia junto com os metadados "title" do schema."""
    schema = compact_schema(_Titled.model_json_schema())

    assert set(schema["properties"]) == {"title", "due_text"}
    assert schema["required"] == ["title"]
    assert schema["properties"]["title"] == {"description": "Título da atividade", "type": "string"}
    assert schema["properties"]["due_text"] == {"description": "Prazo", "type": "string"}
