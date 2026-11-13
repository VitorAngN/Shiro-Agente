"""Habilidades: validar os passos, achar pelo que foi dito e trocar o {x}."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from shiro.application.skills.service import Skills
from shiro.domain.skills.models import Skill
from tests.fakes.agent import SAO_PAULO

NOW = datetime(2026, 11, 13, 19, 0, tzinfo=SAO_PAULO)
KNOWN = {
    "open_program": {"name"},
    "open_url": {"url", "search", "on", "play"},
    "type_text": {"text", "enter"},
}


class Clock:
    def now(self) -> datetime:
        return NOW


class Store:
    def __init__(self) -> None:
        self.rows: dict[str, Skill] = {}

    async def all(self) -> list[Skill]:
        return list(self.rows.values())

    async def put(self, skill: Skill) -> None:
        self.rows[skill.name] = skill

    async def remove(self, name: str) -> bool:
        return self.rows.pop(name, None) is not None


def check(tool: str, args: dict[str, Any]) -> str | None:
    if tool not in KNOWN:
        return "não conheço essa ação"
    extra = set(args) - KNOWN[tool]
    return f"argumento desconhecido {extra}" if extra else None


def steps(*items: tuple[str, dict[str, Any]]) -> str:
    return json.dumps([{"tool": t, "args": a} for t, a in items])


async def test_create_and_use_a_skill() -> None:
    store = Store()
    skills = Skills(store, Clock())
    made = skills.parse(
        "Modo estudo",
        "abre o que eu uso para estudar",
        steps(("open_program", {"name": "Obsidian"}), ("open_url", {"url": "moodle.utfpr.edu.br"})),
        check,
    )
    assert isinstance(made, Skill) and made.name == "modo estudo"
    result = await skills.save(made)
    assert result.ok and "modo estudo" in result.content
    assert skills.match("Shiro, modo estudo.") == [
        ("open_program", {"name": "Obsidian"}),
        ("open_url", {"url": "moodle.utfpr.edu.br"}),
    ]
    assert skills.match("ativa o modo estudo por favor") is not None
    assert skills.match("modo jogo") is None

    reloaded = Skills(store, Clock())
    await reloaded.load()
    assert reloaded.match("modo estudo") is not None
    assert (await reloaded.forget("modo estudo")).ok and reloaded.match("modo estudo") is None


async def test_slot_takes_the_rest_of_the_phrase() -> None:
    skills = Skills(Store(), Clock())
    made = skills.parse(
        "toca no spotify {x}",
        "",
        steps(("open_program", {"name": "Spotify"}), ("type_text", {"text": "{x}", "enter": True})),
        check,
    )
    assert isinstance(made, Skill)
    await skills.save(made)
    assert skills.match("Shiro, toca no Spotify Matuê e Teto.") == [
        ("open_program", {"name": "Spotify"}),
        ("type_text", {"text": "Matuê e Teto", "enter": True}),
    ]
    assert skills.match("toca no spotify") is None


def test_bad_skills_explain_why() -> None:
    skills = Skills(Store(), Clock())
    assert "JSON" in str(skills.parse("x", "", "não é json", check))
    assert "não conheço" in str(skills.parse("x", "", steps(("format_disk", {})), check))
    assert "argumento" in str(skills.parse("x", "", steps(("open_program", {"nome": "a"})), check))
    slot = skills.parse("abre", "", steps(("open_program", {"name": "{x}"})), check)
    assert "{x}" in str(slot)
    assert "pelo menos um" in str(skills.parse("x", "", "[]", check))
