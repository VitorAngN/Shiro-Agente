"""Rotinas do shiro.toml validadas contra as ferramentas reais."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shiro.application.registry import ToolRegistry
from shiro.application.routines import RoutineRules, load_routines
from tests.fakes.agent import FakeTool
from tests.fakes.routines import study_routine


class AppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str


class LevelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=0, le=100)


def test_routines_are_validated_against_real_tools() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("close_app", args_model=AppArgs))
    registry.register(FakeTool("open_app", args_model=AppArgs))
    registry.register(FakeTool("set_volume", args_model=LevelArgs))
    routines, problems = load_routines(study_routine(), registry)
    assert list(routines) == ["estudo"]
    assert len(problems) == 1 and problems[0].startswith("rotina quebrada desligada")
    rules = RoutineRules(routines)
    for spoken in (
        "modo estudo",
        "Ei Shiro, ativa o modo estudo",
        "hora de estudar",
        "rotina estudo",
    ):
        calls = rules(spoken)
        assert calls is not None and [c[0] for c in calls] == [
            "close_app",
            "open_app",
            "set_volume",
        ]
    assert rules("estudo") is None  # uma palavra solta não liga a rotina
    assert rules("modo avião") is None
