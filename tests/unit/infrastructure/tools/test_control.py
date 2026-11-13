"""Controle do PC: endereços, teclas, achar o botão pelo nome e as ferramentas."""

from __future__ import annotations

import ctypes
from collections.abc import Sequence
from datetime import datetime

import httpx
import pytest
from pydantic import ValidationError

from shiro.bootstrap.tools import TOOL_GATES, Desktop, build_registry
from shiro.config.settings import Settings
from shiro.domain.models import RiskLevel
from shiro.domain.ports import ToolContext
from shiro.infrastructure.tools.control import (
    ClickOnTool,
    OpenUrlArgs,
    OpenUrlTool,
    PressKeysTool,
    ReadScreenTool,
    Screen,
    ScreenElement,
    ScreenShot,
    TypeTextTool,
    describe_screen,
    find_element,
    normalize_url,
    parse_keys,
)
from shiro.infrastructure.tools.windows import control as win
from tests.fakes.agent import SAO_PAULO
from tests.fakes.desktop import FakeProbe

CTX = ToolContext(trace_id="t", now=datetime(2026, 11, 13, 10, 0, tzinfo=SAO_PAULO))

PAGE = Screen(
    window="Wikipedia - Google Chrome",
    elements=(
        ScreenElement("Pesquisar na Wikipédia", "campo", 400, 80),
        ScreenElement("Pesquisar", "botão", 600, 80),
        ScreenElement("Página principal", "link", 50, 200),
        ScreenElement("Entrar", "link", 900, 20),
        ScreenElement("Entrar", "botão", 910, 22),
    ),
)


class FakeControl:
    def __init__(self, screen: Screen = PAGE) -> None:
        self.calls: list[tuple[object, ...]] = []
        self._screen = screen

    async def open_url(self, url: str, browser: str) -> None:
        self.calls.append(("open", url, browser))

    async def type_text(self, text: str) -> None:
        self.calls.append(("type", text))

    async def press_keys(self, keys: Sequence[str]) -> None:
        self.calls.append(("keys", tuple(keys)))

    async def paste_text(self, text: str) -> None:
        self.calls.append(("paste", text))

    async def hold_keys(self, keys: Sequence[str], seconds: float) -> None:
        self.calls.append(("hold", tuple(keys), seconds))

    async def scroll(self, notches: int) -> None:
        self.calls.append(("scroll", notches))

    async def capture(self) -> ScreenShot:
        return ScreenShot(png=b"png", left=100, top=50, width=1000, height=500, window="Jogo")

    async def screen(self) -> Screen:
        return self._screen

    async def click(self, x: int, y: int, *, button: str, double: bool) -> None:
        self.calls.append(("click", x, y, button, double))


def test_parse_keys() -> None:
    assert parse_keys("Ctrl + L") == ("ctrl", "l")
    assert parse_keys("controle+shift+esc") == ("ctrl", "shift", "esc")
    assert parse_keys("Enter") == ("enter",)
    assert parse_keys("win") == ("win",)
    assert parse_keys("alt+F4") == ("alt", "f4")
    for bad in ("ctrl+", "ctrl+shift", "hiper+x", "a+b+c+d+e"):
        with pytest.raises(ValueError, match=r"."):
            parse_keys(bad)


def test_urls_only_http() -> None:
    assert normalize_url("youtube.com") == "https://youtube.com"
    assert normalize_url("http://localhost:8080/x") == "http://localhost:8080/x"
    for bad in ("file:///C:/x", "javascript:alert(1)", "nada", "dois nomes.com"):
        with pytest.raises(ValueError, match=r"."):
            normalize_url(bad)


def test_open_url_args() -> None:
    search = OpenUrlArgs(search="Machado de Assis", on="wikipedia")
    assert search.address() == "https://pt.wikipedia.org/w/index.php?search=Machado+de+Assis"
    assert OpenUrlArgs(url="g1.globo.com").address() == "https://g1.globo.com"
    with pytest.raises(ValidationError):
        OpenUrlArgs()
    with pytest.raises(ValidationError):
        OpenUrlArgs(url="x.com", search="y")


def test_find_element_prefers_exact_then_kind() -> None:
    assert find_element(PAGE.elements, "pesquisar") == PAGE.elements[1]
    assert find_element(PAGE.elements, "entrar") == PAGE.elements[4]  # botão antes de link
    assert find_element(PAGE.elements, "pagina principal") == PAGE.elements[2]
    assert find_element(PAGE.elements, "Pagina princpal") == PAGE.elements[2]  # parecido
    assert find_element(PAGE.elements, "configurações") is None
    assert find_element(PAGE.elements, "  ") is None


def test_describe_screen_dedupes() -> None:
    text = describe_screen(PAGE)
    assert text.startswith("Janela: Wikipedia - Google Chrome")
    assert text.count("Entrar (link)") == 1
    assert "Nada" not in describe_screen(Screen("Vazia"))


async def test_tools_drive_the_control() -> None:
    control = FakeControl()
    open_url = OpenUrlTool(control)
    assert open_url.spec.risk is RiskLevel.R1 and open_url.spec.external
    result = await open_url.run(
        OpenUrlArgs(search="steam deck", on="youtube", browser="chrome"), CTX
    )
    assert result.ok and result.say == "Pesquisando steam deck no Youtube."
    assert control.calls[-1] == (
        "open",
        "https://www.youtube.com/results?search_query=steam+deck",
        "chrome",
    )

    typing = TypeTextTool(control)
    assert typing.spec.risk is RiskLevel.R2
    await typing.run(typing.spec.args_model(text="olá, mundo", enter=True), CTX)
    assert control.calls[-2:] == [("type", "olá, mundo"), ("keys", ("enter",))]

    keys = PressKeysTool(control)
    await keys.run(keys.spec.args_model(keys="Ctrl + T"), CTX)
    assert control.calls[-1] == ("keys", ("ctrl", "t"))
    with pytest.raises(ValidationError):
        keys.spec.args_model(keys="ctrl+banana")

    click = ClickOnTool(control)
    done = await click.run(click.spec.args_model(target="pesquisar"), CTX)
    assert done.ok and control.calls[-1] == ("click", 600, 80, "esquerdo", False)
    missing = await click.run(click.spec.args_model(target="Configurações"), CTX)
    assert not missing.ok and "Página principal" in missing.content

    screen = ReadScreenTool(control)
    assert not screen.spec.output_trusted
    read = await screen.run(screen.spec.args_model(), CTX)
    assert "Pesquisar (botão)" in read.content


def test_input_structures_match_windows_sizes() -> None:
    # INPUT tem 40 bytes no Windows 64 bits; o SendInput recusa outro tamanho.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(win._Input) == 40  # pyright: ignore[reportPrivateUsage]
    typed = win.unicode_events("é\n😀")
    assert len(typed) == 2 + 2 + 4  # acento, Enter, emoji em dois pedaços UTF-16
    combo = win.combo_events(("ctrl", "shift", "esc"))
    assert [e.u.ki.wVk for e in combo] == [0x11, 0x10, 0x1B, 0x1B, 0x10, 0x11]
    assert win.combo_events(("ctrl", "l"))[1].u.ki.wVk == ord("L")


async def test_registry_gates_control_tools() -> None:
    settings = Settings()
    async with httpx.AsyncClient() as http:
        registry = build_registry(
            settings, desktop=Desktop(control=FakeControl()), http=http, probe=FakeProbe()
        )
        off = build_registry(
            settings.model_copy(
                update={"policy": settings.policy.model_copy(update={"pc_control": False})}
            ),
            desktop=Desktop(control=FakeControl()),
            http=http,
            probe=FakeProbe(),
        )
    assert {"open_url", "type_text", "click_on"} <= set(registry.names())
    assert "open_url" not in off.names()
    for name in ("open_url", "click_on"):
        assert registry.group_of(name) == "control"
    assert "control" in TOOL_GATES
    for phrase in ("clica em entrar", "abre o youtube", "digita oi", "aperta ctrl c"):
        registry.gate("control", TOOL_GATES["control"])
        assert "control" in registry.groups_for(phrase), phrase


def test_first_video_id_from_results_page() -> None:
    from shiro.infrastructure.tools.youtube import first_video_id

    page = 'x"videoRenderer":{"videoId":"dQw4w9WgXcQ","thumb"... "videoId":"zzzzzzzzzzz"'
    assert first_video_id(page) == "dQw4w9WgXcQ"
    assert first_video_id("<html>nada</html>") is None


async def test_play_opens_the_first_video() -> None:
    class Videos:
        async def first_video(self, query: str) -> str | None:
            return "https://www.youtube.com/watch?v=abc" if query == "matue" else None

    control = FakeControl()
    tool = OpenUrlTool(control, Videos())
    done = await tool.run(OpenUrlArgs(search="matue", on="youtube", play=True), CTX)
    assert control.calls[-1][1] == "https://www.youtube.com/watch?v=abc"
    assert done.say == "Tocando matue no YouTube."
    await tool.run(OpenUrlArgs(search="nada", on="youtube", play=True), CTX)
    assert "results?search_query=nada" in str(control.calls[-1][1])


async def test_program_tools() -> None:
    from shiro.infrastructure.tools.programs import OpenProgramTool, SwitchWindowTool

    class Programs:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def program_names(self) -> list[str]:
            return ["Claude", "Calculadora"]

        def window_titles(self) -> list[str]:
            return ["Wikipedia - Google Chrome"]

        async def launch(self, name: str) -> None:
            self.calls.append(("launch", name))

        async def focus(self, title: str) -> None:
            self.calls.append(("focus", title))

    programs = Programs()
    opened = await OpenProgramTool(programs).run(OpenProgramTool.spec.args_model(name="cloud"), CTX)
    assert opened.ok and programs.calls[-1] == ("launch", "Claude")
    missing = await OpenProgramTool(programs).run(OpenProgramTool.spec.args_model(name="xyz"), CTX)
    assert not missing.ok
    switch = SwitchWindowTool(programs)
    await switch.run(switch.spec.args_model(name="chrome"), CTX)
    assert programs.calls[-1] == ("focus", "Wikipedia - Google Chrome")
    await switch.run(switch.spec.args_model(name="calculadora"), CTX)
    assert programs.calls[-1] == ("launch", "Calculadora")


async def test_write_text_goes_to_the_named_window() -> None:
    from shiro.infrastructure.tools.writing import WriteTextTool

    class Programs:
        def __init__(self) -> None:
            self.focused: list[str] = []

        def program_names(self) -> list[str]:
            return ["Obsidian"]

        def window_titles(self) -> list[str]:
            return ["Notas - Obsidian v1.7"]

        async def launch(self, name: str) -> None:
            raise AssertionError(name)

        async def focus(self, title: str) -> None:
            self.focused.append(title)

    control, programs = FakeControl(), Programs()
    tool = WriteTextTool(control, programs)
    note = "## Compras\n- [ ] leite\n- [ ] pão"
    done = await tool.run(tool.spec.args_model(content=note, window="obsidian"), CTX)
    assert done.ok and programs.focused == ["Notas - Obsidian v1.7"]
    assert control.calls[-1] == ("paste", note)
    missing = await tool.run(tool.spec.args_model(content="x", window="photoshop"), CTX)
    assert not missing.ok and control.calls[-1] == ("paste", note)


async def test_click_falls_back_to_vision_and_new_tools() -> None:
    from shiro.infrastructure.llm.vision import parse_spot
    from shiro.infrastructure.tools.control import (
        HoldKeysTool,
        LookAtScreenTool,
        ScrollTool,
        Spot,
    )

    class Vision:
        async def locate(self, png: bytes, target: str) -> Spot | None:
            return Spot(500, 200, "botão Aceitar") if "aceitar" in target.lower() else None

        async def describe(self, png: bytes, question: str) -> str:
            return "Tela de fila do jogo."

    control = FakeControl(Screen(window="Jogo"))
    click = ClickOnTool(control, Vision())
    done = await click.run(click.spec.args_model(target="Aceitar partida"), CTX)
    assert done.ok and control.calls[-1] == ("click", 600, 150, "esquerdo", False)
    missing = await click.run(click.spec.args_model(target="Sair"), CTX)
    assert not missing.ok and "Olhei" in missing.content

    look = await LookAtScreenTool(control, Vision()).run(LookAtScreenTool.spec.args_model(), CTX)
    assert "fila" in look.content
    await ScrollTool(control).run(ScrollTool.spec.args_model(direction="baixo", amount=3), CTX)
    assert control.calls[-1] == ("scroll", -3)
    await HoldKeysTool(control).run(HoldKeysTool.spec.args_model(keys="shift+w", seconds=2), CTX)
    assert control.calls[-1] == ("hold", ("shift", "w"), 2.0)

    assert parse_spot('{"found": true, "x": 10, "y": 990, "what": "x"}') == Spot(10, 990, "x")
    assert parse_spot('[{"found": true, "x": 1, "y": 2}]') == Spot(1, 2, "")
    assert parse_spot('{"found": false}') is None
    assert parse_spot("bobagem") is None
    assert parse_spot('{"found": true, "x": 5000, "y": 2}') is None
