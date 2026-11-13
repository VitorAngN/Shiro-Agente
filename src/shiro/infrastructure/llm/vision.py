"""Visão da tela pelo Gemini: onde está algo num print e o que aparece nele (ADR-0027).

Conta nos mesmos limites e no mesmo orçamento do Tier 2. O print só sai do PC
quando a SHIRO precisa olhar a tela (clicar no que não tem nome, ler um jogo).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, cast

from shiro.domain.ports import LLMError
from shiro.infrastructure.tools.control import Spot

log = logging.getLogger(__name__)

_LOCATE = (
    "A imagem é o print de uma janela do Windows. Ache isto nela: {target}\\n"
    'Responda só com JSON: {{"found": true ou false, "x": 0 a 1000, "y": 0 a 1000, '
    '"what": "o que você achou, em poucas palavras"}}. x e y são o centro do lugar onde '
    "clicar, em milésimos da largura e da altura da imagem (0,0 = canto de cima à esquerda). "
    "Se não estiver visível, found = false."
)
_DESCRIBE = (
    "A imagem é o print de uma janela do Windows do usuário. Responda em português do "
    "Brasil, em poucas frases, só sobre o que aparece: {question}"
)


class Looker(Protocol):
    async def look(
        self, png: bytes, instruction: str, *, as_json: bool
    ) -> tuple[str, int, int]: ...


class Guard(Protocol):
    async def reserve(self) -> None: ...

    async def record(self, tokens_in: int, tokens_out: int) -> None: ...


def parse_spot(text: str) -> Spot | None:
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(raw, list) and raw:
        raw = cast("list[object]", raw)[0]
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, Any]", raw)
    if not data.get("found"):
        return None
    try:
        x, y = float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    return Spot(x, y, str(data.get("what") or ""))


class GeminiVision:
    def __init__(self, looker: Looker, guard: Guard | None = None) -> None:
        self._looker = looker
        self._guard = guard

    async def _ask(self, png: bytes, instruction: str, *, as_json: bool) -> str:
        if self._guard is not None:
            await self._guard.reserve()
        text, tokens_in, tokens_out = await self._looker.look(png, instruction, as_json=as_json)
        if self._guard is not None:
            await self._guard.record(tokens_in, tokens_out)
        return text

    async def locate(self, png: bytes, target: str) -> Spot | None:
        try:
            text = await self._ask(png, _LOCATE.format(target=target), as_json=True)
        except LLMError as exc:
            log.warning("visão: %s", exc)
            return None
        return parse_spot(text)

    async def describe(self, png: bytes, question: str) -> str:
        try:
            return await self._ask(png, _DESCRIBE.format(question=question), as_json=False)
        except LLMError as exc:
            return f"Não consegui olhar a tela agora ({exc})."
