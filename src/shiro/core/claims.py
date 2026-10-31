"""Detecção de ação alegada (ADR-0011, RF-16).

O modelo pode responder "pronto, marquei" sem ter chamado nenhuma ferramenta.
Esta checagem identifica frases que afirmam uma ação concluída, para o
``AgentLoop`` comparar com o que de fato foi executado no turno.

É uma heurística do lado seguro: um falso positivo custa uma nova tentativa;
um falso negativo é o erro que ela existe para pegar.
"""

from __future__ import annotations

import re

from shiro.core.text import normalize

# Verbos na 1ª pessoa do pretérito perfeito ("marquei", "abri"...).
_PAST_VERBS = (
    "abaixei|abri|adiei|agendei|ajustei|anotei|apaguei|aumentei|baixei|coloquei|conclui|"
    "configurei|criei|defini|deixei|desliguei|diminui|executei|exclui|fechei|fiz|iniciei|"
    "liguei|marquei|mudei|pausei|pulei|registrei|removi|retomei|salvei|silenciei|toquei|troquei"
)
_CLAIMS = re.compile(
    rf"\b(?:{_PAST_VERBS})\b"
    r"|^(?:pronto|feito|prontinho)\b"
    r"|\b(?:foi|esta|ficou|ja esta) (?:marcad|conclui|criad|anotad|adiad|agendad|registrad|"
    r"salv|abert|fechad|ajustad|definid)\w*"
)
_NEGATIONS = {"nao", "nunca", "nem"}
_SENTENCES = re.compile(r"[^.!?\n]+[.!?]?")


def claims_action(text: str) -> bool:
    """``True`` se o texto afirma ter executado uma ação.

    Perguntas são ignoradas ("qual atividade devo marcar?"), assim como
    frases negadas ("não abri o app").
    """
    for raw in _SENTENCES.findall(text):
        sentence = raw.strip()
        if not sentence or sentence.endswith("?"):
            continue
        normalized = normalize(sentence)
        for match in _CLAIMS.finditer(normalized):
            before = normalized[: match.start()].split()[-2:]
            if not _NEGATIONS.intersection(before):
                return True
    return False
