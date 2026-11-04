"""Utilidades comuns às ferramentas nativas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Args(BaseModel):
    """Base dos argumentos: imutável e sem campos extras."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def expect[T: BaseModel](args: BaseModel, model: type[T]) -> T:
    """Garante o tipo dos argumentos já validados pelo agente."""
    if not isinstance(args, model):
        msg = f"argumentos inesperados: {type(args).__name__} (esperado {model.__name__})"
        raise TypeError(msg)
    return args


def br_number(value: float, digits: int = 1) -> str:
    """Formata no padrão brasileiro: ``9.25`` → ``"9,3"``; ``10.0`` → ``"10"``."""
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")
