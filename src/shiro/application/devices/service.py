"""Pareamento e autenticação dos aparelhos (ADR-0022).

O fluxo: o programa do PC pede um código (``start_pairing``) e mostra no QR; o
celular lê e troca o código por uma chave só dele (``complete_pairing``); a
partir daí toda chamada traz a chave (``authenticate``). Desligar um aparelho
(``revoke``) invalida a chave na hora.
"""

from __future__ import annotations

import hmac
from datetime import timedelta

from shiro.domain.devices.models import (
    PAIRING_TTL,
    Device,
    DeviceStore,
    Paired,
    Pairing,
    clean_name,
    hash_token,
    new_secret,
)
from shiro.domain.ids import uuid7
from shiro.domain.ports import Clock

_SEEN_EVERY = timedelta(minutes=1)  # não grava "visto agora" a cada chamada
_MAX_ATTEMPTS = 5  # códigos errados antes de o pareamento aberto ser cancelado


class DeviceRegistry:
    def __init__(self, store: DeviceStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        self._pairing: Pairing | None = None
        self._attempts = 0

    def start_pairing(self) -> Pairing:
        """Abre um pareamento; o anterior, se houver, deixa de valer."""
        self._pairing = Pairing(new_secret(), self._clock.now() + PAIRING_TTL)
        self._attempts = 0
        return self._pairing

    async def complete_pairing(self, code: str, name: str) -> Paired | None:
        """Troca o código pela chave do aparelho; ``None`` se o código não vale."""
        pairing = self._pairing
        if pairing is None:
            return None
        now = self._clock.now()
        if not pairing.valid_at(now):
            self._pairing = None
            return None
        if not hmac.compare_digest(code.encode(), pairing.code.encode()):
            self._attempts += 1
            if self._attempts >= _MAX_ATTEMPTS:
                self._pairing = None
            return None
        self._pairing = None  # uso único
        token = new_secret()
        device = Device(id=uuid7(), name=clean_name(name), created_at=now, last_seen_at=now)
        await self._store.add(device, hash_token(token))
        return Paired(device, token)

    async def authenticate(self, token: str) -> Device | None:
        if not token:
            return None
        device = await self._store.by_token_hash(hash_token(token))
        if device is None or not device.active:
            return None
        now = self._clock.now()
        if device.last_seen_at is None or now - device.last_seen_at >= _SEEN_EVERY:
            await self._store.touch(device.id, now)
        return device

    async def devices(self) -> list[Device]:
        """Os aparelhos ativos, do mais novo para o mais antigo."""
        return [device for device in await self._store.list() if device.active]

    async def revoke(self, device_id: str) -> bool:
        return await self._store.revoke(device_id, self._clock.now())
