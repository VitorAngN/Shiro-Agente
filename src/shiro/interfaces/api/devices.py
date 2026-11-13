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
from shiro.application.devices.confirmations import RemoteConfirmations
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


class ConfirmationInfo(BaseModel):
    id: str
    prompt: str


class ConfirmationAnswer(BaseModel):
    approve: bool


type Lessons = Callable[[], list[dict[str, str]]]


class VoiceResponse(BaseModel):
    heard: str | None
    """O que ela ouviu; ``None`` quando ninguém falou ou não deu para entender."""
    text: str = ""
    tier: str = ""
    latency_ms: int = 0
    tools: list[str] = []


type Voice = Callable[[Device], Awaitable[tuple[str, AgentResult] | None]]
"""Ouve uma frase pelo microfone do PC, responde em voz alta e devolve o que ouviu e a resposta."""


class PairingResponse(BaseModel):
    code: str
    expires_at: str
    host: str
    port: int


async def require_device(request: Request) -> Device:
    """O aparelho dono da chave em ``Authorization: Bearer``; 401 se não houver."""
    registry: DeviceRegistry = request.app.state.registry
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    found = await registry.authenticate(token.strip()) if scheme.lower() == "bearer" else None
    if found is None:
        raise HTTPException(status_code=401, detail="aparelho não pareado ou desligado")
    return found


def create_device_api(
    *,
    registry: DeviceRegistry,
    chat: Chat,
    confirmations: RemoteConfirmations | None = None,
    lessons: Lessons | None = None,
    voice: Voice | None = None,
    can_pair: Callable[[Device], bool] | None = None,
    address: tuple[str, int] = ("127.0.0.1", 8766),
) -> FastAPI:
    api = FastAPI(title="SHIRO · aparelhos", version=__version__, docs_url=None, redoc_url=None)

    api.state.registry = registry

    async def device(request: Request) -> Device:
        return await require_device(request)

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

    @api.get("/v1/confirmations")
    async def get_confirmations(current: Device = paired) -> list[ConfirmationInfo]:
        """Perguntas esperando um sim ou não ("Abrir a Steam?")."""
        waiting = confirmations.pending() if confirmations else []
        return [ConfirmationInfo(id=p.id, prompt=p.prompt) for p in waiting]

    @api.post("/v1/confirmations/{pending_id}")
    async def answer_confirmation(
        pending_id: str, body: ConfirmationAnswer, current: Device = paired
    ) -> dict[str, bool]:
        if confirmations is None or not confirmations.answer(pending_id, body.approve):
            raise HTTPException(status_code=404, detail="essa pergunta já foi respondida ou venceu")
        return {"answered": True}

    @api.post("/v1/voice")
    async def post_voice(current: Device = paired) -> VoiceResponse:
        if voice is None:
            raise HTTPException(status_code=503, detail="a voz não está disponível neste motor")
        try:
            exchange = await voice(current)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"a voz falhou: {exc}") from exc
        if exchange is None:
            return VoiceResponse(heard=None)
        heard, result = exchange
        return VoiceResponse(
            heard=heard,
            text=result.text,
            tier=result.tier.value,
            latency_ms=result.latency_ms,
            tools=[executed.call.name for executed in result.calls],
        )

    @api.post("/v1/pairing")
    async def start_pairing(current: Device = paired) -> PairingResponse:
        """Abre um pareamento para o QR. Só o programa deste PC pode pedir."""
        if can_pair is None or not can_pair(current):
            raise HTTPException(status_code=403, detail="só o programa do PC abre um pareamento")
        pairing = registry.start_pairing()
        return PairingResponse(
            code=pairing.code,
            expires_at=pairing.expires_at.isoformat(),
            host=address[0],
            port=address[1],
        )

    @api.delete("/v1/devices/{device_id}")
    async def revoke_device(device_id: str, current: Device = paired) -> dict[str, bool]:
        """Desliga outro aparelho. Só o programa deste PC pode."""
        if can_pair is None or not can_pair(current):
            raise HTTPException(status_code=403, detail="só o programa do PC desliga aparelhos")
        if device_id == current.id:
            raise HTTPException(status_code=400, detail="o programa do PC não desliga a si mesmo")
        return {"revoked": await registry.revoke(device_id)}

    @api.get("/v1/lessons")
    async def get_lessons(current: Device = paired) -> list[dict[str, str]]:
        return lessons() if lessons else []

    return api
