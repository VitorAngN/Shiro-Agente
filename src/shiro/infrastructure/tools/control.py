"""Controle do PC: abrir sites, digitar, apertar teclas, ler a tela e clicar (ADR-0024).

As ferramentas falam com um ``DesktopControl``; a implementação do Windows
fica em ``windows/control.py``. Tudo o que dá para testar sem Windows (montar
o endereço, ler a combinação de teclas, achar o botão pelo nome) mora aqui.

Riscos: abrir site é R1, como abrir app. Digitar, apertar teclas e clicar são
R2: depois de ler a tela (conteúdo externo), pedem confirmação, porque o texto
de uma página não pode mandar a SHIRO clicar em nada.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Tool, ToolContext, ToolSpec
from shiro.infrastructure.tools._base import Args, expect

Browser = Literal["padrao", "chrome", "edge", "firefox", "brave", "opera"]
SearchSite = Literal["google", "youtube", "wikipedia", "github", "maps"]
MouseButton = Literal["esquerdo", "direito"]

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "wikipedia": "https://pt.wikipedia.org/w/index.php?search={}",
    "github": "https://github.com/search?q={}",
    "maps": "https://www.google.com/maps/search/{}",
}


# --- teclas -----------------------------------------------------------------

KEY_NAMES: dict[str, str] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "controle": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "win": "win",
    "windows": "win",
    "super": "win",
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "tab": "tab",
    "space": "space",
    "espaco": "space",
    "backspace": "backspace",
    "apagar": "backspace",
    "delete": "delete",
    "del": "delete",
    "up": "up",
    "cima": "up",
    "down": "down",
    "baixo": "down",
    "left": "left",
    "esquerda": "left",
    "right": "right",
    "direita": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "printscreen": "printscreen",
    "capslock": "capslock",
    **{f"f{n}": f"f{n}" for n in range(1, 13)},
}
_MODIFIERS = frozenset({"ctrl", "shift", "alt", "win"})
_MAX_KEYS = 4


def parse_keys(combo: str) -> tuple[str, ...]:
    """``"Ctrl + L"`` → ``("ctrl", "l")``. Letras e números valem sozinhos."""
    parts = [_plain(part).replace(" ", "") for part in re.split(r"\s*\+\s*", combo.strip())]
    keys: list[str] = []
    for part in parts:
        if not part:
            msg = f"combinação de teclas inválida: {combo!r}"
            raise ValueError(msg)
        if part in KEY_NAMES:
            keys.append(KEY_NAMES[part])
        elif re.fullmatch(r"[a-z0-9]", part):
            keys.append(part)
        else:
            msg = f"tecla desconhecida: {part!r}"
            raise ValueError(msg)
    if len(keys) > _MAX_KEYS:
        msg = f"no máximo {_MAX_KEYS} teclas por vez"
        raise ValueError(msg)
    if all(key in _MODIFIERS for key in keys) and keys != ["win"]:
        msg = "falta a tecla principal (ex.: ctrl+c)"
        raise ValueError(msg)
    return tuple(keys)


# --- tela -------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenElement:
    """Algo clicável na janela: nome acessível, tipo e o centro na tela."""

    name: str
    kind: str
    x: int
    y: int


@dataclass(frozen=True)
class Screen:
    window: str
    elements: tuple[ScreenElement, ...] = field(default=())


# Preferência quando dois elementos têm o mesmo nome: o que se clica primeiro.
_KIND_RANK: dict[str, int] = {
    "botão": 0,
    "link": 1,
    "item de menu": 2,
    "aba": 3,
    "campo": 4,
    "caixa de seleção": 5,
    "opção": 6,
    "lista": 7,
    "item": 8,
    "texto": 9,
}
_MIN_RATIO = 0.72


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def find_element(elements: Sequence[ScreenElement], wanted: str) -> ScreenElement | None:
    """O elemento cujo nome mais se parece com ``wanted`` (igual > começa > contém > parecido)."""
    target = _plain(wanted)
    if not target:
        return None
    best: tuple[tuple[float, int, int], ScreenElement] | None = None
    for element in elements:
        name = _plain(element.name)
        if not name:
            continue
        if name == target:
            score = 4.0
        elif name.startswith(target) or (target.startswith(name) and len(name) >= 3):
            score = 3.0
        elif re.search(rf"\b{re.escape(target)}\b", name):
            score = 2.5
        elif target in name:
            score = 2.0
        else:
            ratio = difflib.SequenceMatcher(None, target, name).ratio()
            if ratio < _MIN_RATIO:
                continue
            score = 1.0 + ratio
        key = (score, -_KIND_RANK.get(element.kind, 10), -len(name))
        if best is None or key > best[0]:
            best = (key, element)
    return best[1] if best else None


def describe_screen(screen: Screen, limit: int = 40) -> str:
    seen: dict[str, None] = {}
    for element in screen.elements:
        label = f"{element.name} ({element.kind})"
        seen.setdefault(label, None)
        if len(seen) >= limit:
            break
    if not seen:
        return f"Janela: {screen.window}. Não achei nada clicável com nome."
    return f"Janela: {screen.window}\nElementos:\n" + "\n".join(f"- {s}" for s in seen)


# --- porta ------------------------------------------------------------------


class DesktopControl(Protocol):
    async def open_url(self, url: str, browser: Browser) -> None: ...

    async def type_text(self, text: str) -> None:
        """Digita na janela em uso (a da SHIRO fica de fora)."""
        ...

    async def press_keys(self, keys: Sequence[str]) -> None: ...

    async def screen(self) -> Screen:
        """Elementos com nome da janela em uso (a da SHIRO fica de fora)."""
        ...

    async def click(self, x: int, y: int, *, button: MouseButton, double: bool) -> None: ...


# --- abrir sites ------------------------------------------------------------


def normalize_url(raw: str) -> str:
    text = raw.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        msg = "só endereços http ou https"
        raise ValueError(msg)
    if " " in text or ("." not in parsed.hostname and parsed.hostname != "localhost"):
        msg = f"endereço inválido: {raw!r}"
        raise ValueError(msg)
    return text


class OpenUrlArgs(Args):
    url: str | None = Field(
        default=None, max_length=500, description="Endereço do site (ex.: youtube.com)"
    )
    search: str | None = Field(
        default=None, max_length=200, description="O que pesquisar, quando não é um endereço"
    )
    on: SearchSite = Field(default="google", description="Onde pesquisar (só com search)")
    browser: Browser = Field(default="padrao", description="Navegador; padrao = o do Windows")
    play: bool = Field(
        default=False, description="Com on=youtube: já abre e toca o primeiro vídeo da busca"
    )

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str | None) -> str | None:
        return normalize_url(value) if value else None

    @model_validator(mode="after")
    def _one_target(self) -> OpenUrlArgs:
        if bool(self.url) == bool(self.search and self.search.strip()):
            msg = "informe url ou search (um dos dois)"
            raise ValueError(msg)
        return self

    def address(self) -> str:
        if self.url:
            return self.url
        return _SEARCH_URLS[self.on].format(quote_plus((self.search or "").strip()))


class VideoFinder(Protocol):
    async def first_video(self, query: str) -> str | None:
        """Endereço do primeiro vídeo da busca, ou ``None``."""
        ...


class OpenUrlTool:
    spec = ToolSpec(
        name="open_url",
        description=(
            "Abre um site ou uma pesquisa no navegador do PC (Google, YouTube, Wikipedia...). "
            "Use para 'abre o youtube', 'pesquisa X no Google', 'procura X na Wikipedia', "
            "'toca X no YouTube' (search=X, on=youtube, play=true)."
        ),
        args_model=OpenUrlArgs,
        risk=RiskLevel.R1,
        timeout_s=15.0,
        external=True,
        group="control",
    )

    def __init__(self, control: DesktopControl, videos: VideoFinder | None = None) -> None:
        self._control = control
        self._videos = videos

    def describe(self, args: BaseModel) -> str:
        parsed = expect(args, OpenUrlArgs)
        if parsed.play and parsed.search:
            return f"tocar {parsed.search} no YouTube"
        return f"abrir {parsed.address()}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        parsed = expect(args, OpenUrlArgs)
        if parsed.play and parsed.search and parsed.on == "youtube" and self._videos:
            video = await self._videos.first_video(parsed.search.strip())
            if video is not None:
                await self._control.open_url(video, parsed.browser)
                return ToolResult.success(
                    f"Tocando: {video}", say=f"Tocando {parsed.search.strip()} no YouTube."
                )
        await self._control.open_url(parsed.address(), parsed.browser)
        if parsed.search:
            say = f"Pesquisando {parsed.search.strip()} no {parsed.on.capitalize()}."
        else:
            say = f"Abrindo {urlparse(parsed.address()).hostname or parsed.address()}."
        return ToolResult.success(f"Aberto: {parsed.address()}", say=say.replace("www.", ""))


# --- digitar e teclas -------------------------------------------------------


class TypeTextArgs(Args):
    text: str = Field(min_length=1, max_length=2000, description="Texto exato para digitar")
    enter: bool = Field(default=False, description="Aperta Enter no fim (enviar, pesquisar)")


class TypeTextTool:
    spec = ToolSpec(
        name="type_text",
        description=(
            "Digita um texto na janela que está em uso, como se fosse o teclado. "
            "Use enter=true para enviar ou pesquisar depois de digitar."
        ),
        args_model=TypeTextArgs,
        risk=RiskLevel.R2,
        timeout_s=30.0,
        group="control",
    )

    def __init__(self, control: DesktopControl) -> None:
        self._control = control

    def describe(self, args: BaseModel) -> str:
        parsed = expect(args, TypeTextArgs)
        preview = parsed.text if len(parsed.text) <= 60 else parsed.text[:57] + "..."
        return f'digitar "{preview}"' + (" e apertar Enter" if parsed.enter else "")

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        parsed = expect(args, TypeTextArgs)
        await self._control.type_text(parsed.text)
        if parsed.enter:
            await self._control.press_keys(("enter",))
        return ToolResult.success("Digitado.", say="Pronto, digitei.")


class PressKeysArgs(Args):
    keys: str = Field(
        min_length=1,
        max_length=60,
        description="Tecla ou combinação: enter, esc, tab, ctrl+c, ctrl+l, alt+tab, win+d, f5",
    )

    @field_validator("keys")
    @classmethod
    def _known(cls, value: str) -> str:
        return "+".join(parse_keys(value))


class PressKeysTool:
    spec = ToolSpec(
        name="press_keys",
        description="Aperta uma tecla ou um atalho do teclado na janela em uso.",
        args_model=PressKeysArgs,
        risk=RiskLevel.R2,
        timeout_s=10.0,
        group="control",
    )

    def __init__(self, control: DesktopControl) -> None:
        self._control = control

    def describe(self, args: BaseModel) -> str:
        return f"apertar {expect(args, PressKeysArgs).keys}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        keys = expect(args, PressKeysArgs).keys
        await self._control.press_keys(tuple(keys.split("+")))
        return ToolResult.success(f"Apertei {keys}.", say=f"Apertei {keys.replace('+', ' ')}.")


# --- ler a tela e clicar ----------------------------------------------------


class ReadScreenArgs(Args):
    pass


class ReadScreenTool:
    spec = ToolSpec(
        name="read_screen",
        description=(
            "Lista os botões, links e campos da janela em uso, pelo nome. "
            "Use antes de clicar quando não souber o nome exato."
        ),
        args_model=ReadScreenArgs,
        risk=RiskLevel.R0,
        timeout_s=20.0,
        output_trusted=False,
        group="control",
    )

    def __init__(self, control: DesktopControl) -> None:
        self._control = control

    def describe(self, args: BaseModel) -> str:
        return "ler a janela em uso"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        screen = await self._control.screen()
        return ToolResult.success(describe_screen(screen), say=f"Estou vendo {screen.window}.")


class ClickArgs(Args):
    target: str = Field(
        min_length=1, max_length=120, description="Nome do botão, link ou campo (como aparece)"
    )
    button: MouseButton = "esquerdo"
    double: bool = Field(default=False, description="Clique duplo")


class ClickOnTool:
    spec = ToolSpec(
        name="click_on",
        description=(
            "Clica num botão, link, aba ou campo da janela em uso, pelo nome que aparece na tela."
        ),
        args_model=ClickArgs,
        risk=RiskLevel.R2,
        timeout_s=20.0,
        group="control",
    )

    def __init__(self, control: DesktopControl) -> None:
        self._control = control

    def describe(self, args: BaseModel) -> str:
        return f'clicar em "{expect(args, ClickArgs).target}"'

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        parsed = expect(args, ClickArgs)
        screen = await self._control.screen()
        found = find_element(screen.elements, parsed.target)
        if found is None:
            names = list(dict.fromkeys(e.name for e in screen.elements))[:12]
            hint = f" Tem: {', '.join(names)}." if names else ""
            return ToolResult.failure(
                f'Não achei "{parsed.target}" na janela {screen.window}.{hint}'
            )
        await self._control.click(found.x, found.y, button=parsed.button, double=parsed.double)
        return ToolResult.success(
            f"Cliquei em {found.name} ({found.kind}) na janela {screen.window}.",
            say=f"Cliquei em {found.name}.",
        )


def control_tools(control: DesktopControl, videos: VideoFinder | None = None) -> list[Tool]:
    return [
        OpenUrlTool(control, videos),
        TypeTextTool(control),
        PressKeysTool(control),
        ReadScreenTool(control),
        ClickOnTool(control),
    ]
