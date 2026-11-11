"""API dos aparelhos (ADR-0022): o que o celular e o programa do PC usam para falar com o motor.

Diferente do painel (ADR-0019), esta API é feita para ser alcançada de outro
aparelho, pela rede privada do Tailscale. Por isso não há cookie nem sessão de
navegador: toda chamada traz a chave do aparelho em ``Authorization: Bearer``.
A única rota aberta é a de pareamento, que troca o código de uso único do QR
pela chave.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from shiro import __version__
from shiro.application.devices.service import DeviceRegistry
from shiro.domain.devices.models import MAX_NAME, Device
from shiro.domain.models import AgentResult

MAX_TEXT = 2000

type Chat = Callable[[str, Device], Awaitable[AgentResult]]
"""Roda um turno do agente pedido por um aparelho."""


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=MAX_NAME)


class PairResponse(BaseModel):
    device_id: str
    name: str
    token: str


class DeviceInfo(BaseModel):
    id: str
    name: str
    created_at: str
    last_seen_at: str | None

    @classmethod
    def of(cls, device: Device) -> DeviceInfo:
        seen = device.last_seen_at.isoformat() if device.last_seen_at else None
        return cls(
            id=device.id,
            name=device.name,
            created_at=device.created_at.isoformat(),
            last_seen_at=seen,
        )


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class ChatResponse(BaseModel):
    text: str
    tier: str
    latency_ms: int
    tools: list[str]


def create_device_api(*, registry: DeviceRegistry, chat: Chat) -> FastAPI:
    api = FastAPI(title="SHIRO · aparelhos", version=__version__, docs_url=None, redoc_url=None)

    async def device(request: Request) -> Device:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        found = await registry.authenticate(token.strip()) if scheme.lower() == "bearer" else None
        if found is None:
            raise HTTPException(status_code=401, detail="aparelho não pareado ou desligado")
        return found

    paired = Depends(device)

    @api.post("/v1/pair")
    async def pair(body: PairRequest) -> PairResponse:
        result = await registry.complete_pairing(body.code, body.name)
        if result is None:
            raise HTTPException(status_code=403, detail="código inválido ou vencido; gere outro")
        return PairResponse(device_id=result.device.id, name=result.device.name, token=result.token)

    @api.get("/v1/me")
    async def me(current: Device = paired) -> DeviceInfo:
        return DeviceInfo.of(current)

    @api.get("/v1/devices")
    async def devices(current: Device = paired) -> list[DeviceInfo]:
        return [DeviceInfo.of(d) for d in await registry.devices()]

    @api.delete("/v1/me")
    async def unlink(current: Device = paired) -> dict[str, bool]:
        """O aparelho se desliga sozinho (sair do app); os outros, só pelo PC."""
        return {"revoked": await registry.revoke(current.id)}

    @api.post("/v1/chat")
    async def post_chat(body: ChatRequest, current: Device = paired) -> ChatResponse:
        result = await chat(body.text, current)
        return ChatResponse(
            text=result.text,
            tier=result.tier.value,
            latency_ms=result.latency_ms,
            tools=[executed.call.name for executed in result.calls],
        )

    return api
