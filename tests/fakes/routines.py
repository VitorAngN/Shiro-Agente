"""Rotina de exemplo (modo estudo) usada nos testes."""

from __future__ import annotations

from shiro.config.settings import RoutineSettings


def study_routine() -> dict[str, RoutineSettings]:
    return {
        "estudo": RoutineSettings.model_validate(
            {
                "description": "fecha distrações e abre o VS Code",
                "aliases": ["hora de estudar"],
                "steps": [
                    {"tool": "close_app", "args": {"app": "discord"}},
                    {"tool": "open_app", "args": {"app": "vscode"}},
                    {"tool": "set_volume", "args": {"level": 30}},
                ],
            }
        ),
        "quebrada": RoutineSettings.model_validate(
            {"steps": [{"tool": "nao_existe"}, {"tool": "set_volume", "args": {"level": 900}}]}
        ),
    }
