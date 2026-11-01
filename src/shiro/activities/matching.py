"""Encontrar a atividade de que o usuário está falando ("o trabalho de cálculo")."""

from __future__ import annotations

from collections.abc import Sequence

from shiro.activities.models import Activity
from shiro.core.text import normalize

_STOPWORDS = {
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "meu",
    "minha",
    "meus",
    "minhas",
    "pra",
    "para",
    "atividade",
    "tarefa",
}


def _tokens(text: str) -> set[str]:
    return {word for word in normalize(text).split() if word not in _STOPWORDS}


def find(query: str, activities: Sequence[Activity]) -> list[Activity]:
    """Atividades que combinam com a consulta, da melhor para a pior.

    Título idêntico vence; senão, conta quantas palavras da consulta aparecem no
    título (e no contexto). Só entram atividades que contêm todas as palavras
    relevantes da consulta.
    """
    wanted = _tokens(query)
    if not wanted:
        return []
    exact = [a for a in activities if _tokens(a.title) == wanted]
    if exact:
        return exact
    scored: list[tuple[int, Activity]] = []
    for activity in activities:
        have = _tokens(activity.title) | _tokens(activity.context or "")
        if wanted <= have:
            scored.append((len(have - wanted), activity))
    return [activity for _, activity in sorted(scored, key=lambda item: item[0])]
