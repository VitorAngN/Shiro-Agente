"""Regras do Tier 0 para criar atividades e lembretes sem LLM (ADR-0014).

O modelo local às vezes responde "anotado" sem chamar a ferramenta, ou corta o
prazo ("às 8h" em vez de "amanhã às 8h"). As frases mais comuns têm forma fixa
e são resolvidas aqui, com a mesma localização de prazos usada para ancorar os
argumentos do modelo:

* "tenho prova de física dia 12 às 19h"
* "tenho que entregar o relatório sexta"
* "anota que eu preciso comprar café"
* "me lembra de tirar a roupa do varal às seis"

A gramática é estrita: o prazo tem de estar no fim da frase e ser o único. Na
dúvida, a regra não casa e o pedido vai para o modelo.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from shiro.activities import dates

type Calls = list[tuple[str, dict[str, object]]]

_WAKE = {"ei", "ok", "hey", "oi"}
_POLITE = (("por", "favor"), ("pf",), ("pfv",))
_ARTICLES = {"o", "a", "os", "as", "um", "uma", "uns", "umas"}
_TRAILING = {"e", "de", "do", "da", "pra", "para", "que", "no", "na", "ate", "em", "o", "a"}
_VAGUE = (("daqui", "a", "pouco"), ("mais", "tarde"), ("logo",), ("depois",))
_MAX_TITLE_WORDS = 12
# Título que não diz o quê: a SHIRO precisa perguntar, então fica com o modelo.
_GENERIC = {"atividade", "atividades", "tarefa", "tarefas", "coisa", "coisas", "algo", "isso"}

# Coisas que alguém "tem" com prazo. Normalizadas (sem acento).
_NOUNS = (
    "prova|provas|trabalho|trabalhos|entrega|reuniao|consulta|apresentacao|seminario|lista"
    "|atividade|atividades|exercicio|exercicios|relatorio|projeto|tarefa|compromisso|aula"
    "|dentista|medico|exame|teste|simulado|palestra|entrevista|redacao|monitoria"
)

_REMIND = re.compile(
    r"^(?:me\s+)?(?:lembra|lembre|lembrar|avisa|avise)(?:\s+me)?\s+(?:de|que|pra|para)\s+"
    r"(?P<rest>.+)$"
)
_NOTE = re.compile(
    r"^(?:anota|anote|registra|registre|adiciona|adicione|salva|salve)(?:\s+ai)?"
    r"(?:\s+(?:na lista|nas atividades|na agenda|nas tarefas))?(?:\s+que)?(?:\s+eu)?"
    r"(?:\s+(?:tenho que|tenho de|preciso|vou ter|tenho|devo))?\s+(?P<rest>.+)$"
)
_HAVE = re.compile(
    r"^(?:eu\s+)?(?:tenho|vou ter)\s+"
    rf"(?P<rest>(?:(?:uma?|umas|uns)\s+)?(?:{_NOUNS})\b.*)$"
)
_MUST = re.compile(r"^(?:eu\s+)?(?:tenho que|tenho de)\s+(?P<rest>.+)$")

# (padrão, ferramenta, exige prazo)
_RULES: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (_REMIND, "create_reminder", True),
    (_NOTE, "create_activity", False),
    (_HAVE, "create_activity", True),
    (_MUST, "create_activity", True),
)


class ActivityRules:
    """Regra do Tier 0 plugada no roteador pela composição (``app.py``)."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now

    def __call__(self, text: str) -> Calls | None:
        if text.rstrip().endswith("?"):
            return None
        tokens = _trim(dates.words(text))
        plain = " ".join(p for _, p in tokens)
        for pattern, tool, needs_date in _RULES:
            if match := pattern.match(plain):
                start = len(plain[: match.start("rest")].split())
                return self._build(tool, tokens[start:], needs_date=needs_date)
        return None

    def _build(self, tool: str, body: list[tuple[str, str]], *, needs_date: bool) -> Calls | None:
        spans = dates.locate(" ".join(t for t, _ in body), now=self._now())
        if len(spans) > 1 or (spans and spans[0].end != len(body)):
            return None  # prazo no meio ou mais de um: o modelo decide
        span = spans[0] if spans else None
        if span is None and needs_date:
            return None
        title = _tidy(body[: span.start] if span else body)
        if not title:
            return None
        if tool == "create_reminder":
            assert span is not None  # noqa: S101 - garantido por needs_date
            return [(tool, {"text": title, "when_text": span.text})]
        args: dict[str, object] = {"title": title}
        if span is not None:
            args["due_text"] = span.text
        return [(tool, args)]


def _trim(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Tira "ei shiro" do começo e "por favor" do fim."""
    plain = [p for _, p in tokens]
    if len(plain) > 1 and plain[0] in _WAKE and plain[1] == "shiro":
        tokens = tokens[2:]
    elif plain[:1] == ["shiro"]:
        tokens = tokens[1:]
    for suffix in _POLITE:
        if tuple(p for _, p in tokens[-len(suffix) :]) == suffix:
            tokens = tokens[: -len(suffix)]
            break
    return tokens


def _tidy(tokens: list[tuple[str, str]]) -> str:
    """Título limpo: sem artigo no começo, sem conectivos e "daqui a pouco" no fim."""
    changed = True
    while changed and tokens:
        changed = False
        for phrase in _VAGUE:
            if tuple(p for _, p in tokens[-len(phrase) :]) == phrase:
                tokens, changed = tokens[: -len(phrase)], True
        if tokens and tokens[-1][1] in _TRAILING:
            tokens, changed = tokens[:-1], True
    if tokens and tokens[0][1] in _ARTICLES:
        tokens = tokens[1:]
    if not tokens or len(tokens) > _MAX_TITLE_WORDS:
        return ""
    if " ".join(p for _, p in tokens) in _GENERIC:
        return ""
    return " ".join(t for t, _ in tokens)
