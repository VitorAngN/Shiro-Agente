"""Aparelhos ligados à SHIRO (celular, outro PC) e as regras do pareamento (ADR-0022).

Cada aparelho tem a própria chave. O banco guarda só o SHA-256 dela: a chave é
aleatória e longa (256 bits), então um hash simples basta e quem ler o banco
não consegue se passar pelo aparelho.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

PAIRING_TTL = timedelta(minutes=2)
MAX_NAME = 40


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(name: str) -> str:
    """Nome que aparece na lista de aparelhos: uma linha, sem caracteres de controle."""
    one_line = " ".join(name.split())
    return "".join(ch for ch in one_line if ch.isprintable())[:MAX_NAME] or "Aparelho"


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class Pairing:
    """Código de uso único mostrado no QR; vale por ``PAIRING_TTL``."""

    code: str
    expires_at: datetime

    def valid_at(self, now: datetime) -> bool:
        return now < self.expires_at


@dataclass(frozen=True)
class Paired:
    """Resultado do pareamento. ``token`` só existe aqui: vai para o aparelho e não é guardado."""

    device: Device
    token: str


class DeviceStore(Protocol):
    async def add(self, device: Device, token_hash: str) -> None: ...

    async def by_token_hash(self, token_hash: str) -> Device | None: ...

    async def list(self) -> list[Device]: ...

    async def touch(self, device_id: str, seen_at: datetime) -> None: ...

    async def revoke(self, device_id: str, at: datetime) -> bool:
        """``True`` se havia um aparelho ativo com esse id."""
        ...
