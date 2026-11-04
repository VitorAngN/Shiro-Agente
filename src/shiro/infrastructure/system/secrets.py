"""Chaves de API: Gerenciador de Credenciais do Windows, via ``keyring`` (ameaça A-06).

Ordem de busca: variável de ambiente padrão do provedor (útil em CI e testes)
e depois o cofre do sistema. As chaves nunca ficam no ``shiro.toml``, nem em
logs, nem no repositório.
"""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "SHIRO"
PROVIDERS = ("gemini", "anthropic", "openai")
ENV_VARS = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class SecretError(Exception):
    """O cofre de credenciais não está disponível."""


def _check(provider: str) -> None:
    if provider not in PROVIDERS:
        msg = f"provedor desconhecido: {provider!r} (use {', '.join(PROVIDERS)})"
        raise ValueError(msg)


def get_api_key(provider: str) -> str | None:
    _check(provider)
    from_env = os.environ.get(ENV_VARS[provider], "").strip()
    if from_env:
        return from_env
    try:
        stored = keyring.get_password(SERVICE, provider)
    except KeyringError:
        return None
    return stored.strip() if stored else None


def key_source(provider: str) -> str | None:
    """De onde a chave viria: "ambiente", "cofre" ou ``None``. Nunca devolve a chave."""
    _check(provider)
    if os.environ.get(ENV_VARS[provider], "").strip():
        return "ambiente"
    try:
        return "cofre" if keyring.get_password(SERVICE, provider) else None
    except KeyringError:
        return None


def set_api_key(provider: str, value: str) -> None:
    _check(provider)
    if not value.strip():
        msg = "a chave está vazia"
        raise ValueError(msg)
    try:
        keyring.set_password(SERVICE, provider, value.strip())
    except KeyringError as exc:
        msg = f"cofre de credenciais indisponível: {exc}"
        raise SecretError(msg) from exc


def delete_api_key(provider: str) -> bool:
    _check(provider)
    try:
        keyring.delete_password(SERVICE, provider)
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        msg = f"cofre de credenciais indisponível: {exc}"
        raise SecretError(msg) from exc
    return True
