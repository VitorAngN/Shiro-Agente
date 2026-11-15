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
    "Brasil, só sobre o que aparece: {question}"
)


_READ = (
    "A imagem é o print de uma janela do Windows. Pegue o texto principal que aparece (a "
    "página do livro, o artigo, o documento), na ordem de leitura. Deixe de fora menus, "
    "botões, barras do programa, cabeçalhos e números de página. Junte palavras quebradas "
    "por hífen no fim da linha. Separe os parágrafos com uma linha em branco. Responda só "
    "com o texto, sem comentários."
)
_READ_TRANSLATED = (
    "A imagem é o print de uma janela do Windows. Pegue o texto principal que aparece (a "
    "página do livro, o artigo, o documento), sem menus, botões, cabeçalhos nem números de "
    "página, e traduza para {language}, de forma natural e fiel. Responda só com JSON: "
    '{{"traducao": "o texto inteiro traduzido"}}. Mantenha os parágrafos, separados por '
    "uma linha em branco. Não inclua o texto original."
)


def translation_from(text: str) -> str:
    """Só a tradução, mesmo que o modelo mande mais campos ou texto em volta do JSON."""
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return text.strip()
        try:
            raw = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return text.strip()
    if isinstance(raw, dict):
        data = cast("dict[str, Any]", raw)
        for key in ("traducao", "tradução", "translation", "texto"):
            value = data.get(key)
            if isinstance(value, str):
                return value.strip()  # vazio = não havia texto: nunca falar o JSON
        return ""
    return text.strip()


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

    async def read_text(self, png: bytes, translate_to: str | None) -> str:
        try:
            if not translate_to:
                return await self._ask(png, _READ, as_json=False)
            answer = await self._ask(
                png, _READ_TRANSLATED.format(language=translate_to), as_json=True
            )
        except LLMError as exc:
            return f"Não consegui olhar a tela agora ({exc})."
        return translation_from(answer)

    async def describe(self, png: bytes, question: str) -> str:
        try:
            return await self._ask(png, _DESCRIBE.format(question=question), as_json=False)
        except LLMError as exc:
            return f"Não consegui olhar a tela agora ({exc})."
