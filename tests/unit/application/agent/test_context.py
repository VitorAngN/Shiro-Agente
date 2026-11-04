"""Contexto do pedido: memórias depois do prefixo em cache."""

from __future__ import annotations

from shiro.application.agent.context import ContextBuilder
from shiro.domain.models import Role


def test_memories_go_after_the_cached_prefix() -> None:
    builder = ContextBuilder(assistant_name="Shiro")
    plain = builder.build([], "oi")
    with_memory = builder.build([], "qual meu time?", ["eu torço pro Coritiba"])
    assert with_memory[0] == plain[0]  # a persona (prefixo em cache) não muda
    assert with_memory[1].role is Role.SYSTEM and "Coritiba" in with_memory[1].content
    assert with_memory[-1].content == "qual meu time?"
