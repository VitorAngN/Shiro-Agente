"""Texto na fronteira da voz: o que a SHIRO fala e o que ela ouviu.

* ``for_speech``: deixa a resposta pronta para o sintetizador ("23h59" vira
  "23 e 59", "%" vira "por cento", sem marcação de Markdown);
* ``sentences``: divide a resposta em frases, para começar a falar a primeira
  enquanto a próxima ainda está sendo sintetizada;
* ``clean_transcript``: descarta frases que o Whisper inventa no silêncio;
* ``yes_or_no``: interpreta a resposta a uma confirmação.
"""

from __future__ import annotations

import re

from shiro.domain.text import normalize

_MARKDOWN = re.compile(r"[*_`#>|]+")
_LINK = re.compile(r"https?://\S+")
_TIME_HM = re.compile(r"\b(\d{1,2})h(\d{2})\b")
_TIME_H = re.compile(r"\b(\d{1,2})h\b")
_PERCENT = re.compile(r"(\d)\s*%")
_DEGREES = re.compile(r"(\d)\s*°\s*C?\b")
_MONEY = re.compile(r"R\$\s*(\d+(?:[.,]\d+)?)")
_SPACES = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_MIN_SENTENCE = 25


def for_speech(text: str) -> str:
    """Resposta escrita → texto que soa bem falado."""
    spoken = _LINK.sub("o link na tela", text)
    spoken = _MARKDOWN.sub(" ", spoken)
    spoken = _TIME_HM.sub(lambda m: f"{int(m[1])} e {m[2]}", spoken)
    spoken = _TIME_H.sub(lambda m: f"{int(m[1])} {'hora' if int(m[1]) == 1 else 'horas'}", spoken)
    spoken = _PERCENT.sub(r"\1 por cento", spoken)
    spoken = _DEGREES.sub(r"\1 graus", spoken)
    spoken = _MONEY.sub(r"\1 reais", spoken)
    return _SPACES.sub(" ", spoken).strip()


def sentences(text: str) -> list[str]:
    """Frases para sintetizar uma a uma. Frases muito curtas vão junto com a seguinte."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) < _MIN_SENTENCE:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


# Frases que o Whisper costuma "ouvir" em silêncio ou ruído (vêm de legendas de vídeos).
_HALLUCINATIONS = (
    "amara org",
    "legendas pela comunidade",
    "legenda adriana zanotto",
    "obrigado por assistir",
    "inscreva se no canal",
    "se inscreva no canal",
    "ate o proximo video",
)
_HALLUCINATION_ONLY = {"obrigado", "obrigada", "tchau", "e ai", "musica", "aplausos", "risos"}


def clean_transcript(text: str) -> str:
    """Texto transcrito, ou ``""`` se for alucinação conhecida do Whisper."""
    stripped = _SPACES.sub(" ", text).strip()
    plain = normalize(stripped).replace(".", " ").replace("-", " ")
    plain = _SPACES.sub(" ", plain).strip()
    if not plain or plain in _HALLUCINATION_ONLY:
        return ""
    if any(phrase in plain for phrase in _HALLUCINATIONS):
        return ""
    return stripped


_YES = re.compile(
    r"^(?:sim|pode|pode sim|confirmo|confirmado|claro|isso|isso mesmo|manda|manda ver|ok|"
    r"beleza|fechou|faz|faz isso|vai|pode fazer|pode ir|com certeza|positivo|uhum|aham)\b"
)
_NO = re.compile(
    r"^(?:nao|negativo|cancela|cancelar|para|pare|esquece|deixa|deixa pra la|nem|nunca|"
    r"melhor nao|agora nao)\b"
)


def yes_or_no(text: str) -> bool | None:
    """``True`` para sim, ``False`` para não, ``None`` se não deu para saber."""
    plain = normalize(text).replace(",", " ").replace(".", " ").replace("!", " ")
    plain = _SPACES.sub(" ", plain).strip()
    plain = re.sub(r"^(?:ei |ok )?shiro ", "", plain)
    if _NO.match(plain):
        return False
    if _YES.match(plain):
        return True
    return None
