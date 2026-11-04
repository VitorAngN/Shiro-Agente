"""Reconhecimento restrito de comandos: escolher, entre frases conhecidas, a que o áudio diz.

A transcrição livre do Whisper erra justamente nos comandos curtos: o começo da
fala some ("pausa a música" vira "Ausa música") ou um nome em inglês vira outra
palavra ("abra a Steam" vira "Abra, Einstein"). Assistentes como o Home Assistant
resolvem isso reconhecendo contra uma lista de frases conhecidas em vez de
transcrever livremente. Aqui o próprio Whisper faz o papel de juiz: mede quanto
cada comando conhecido explica o áudio (média do log da probabilidade por token)
e a regra abaixo decide se algum ganhou com folga.

Tudo é comparado com a nota da própria transcrição livre, medida do mesmo jeito.
Uma pergunta livre ("me conta uma piada") explica o áudio muito melhor que
qualquer comando e passa adiante sem mudança.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    """Uma frase conhecida e a ação que ela dispara (frases da mesma ação não competem)."""

    phrase: str
    action: str


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: float


@dataclass(frozen=True)
class RescoreRule:
    """Quando trocar a transcrição livre por um comando conhecido.

    Args:
        max_words: só frases curtas; pedidos longos são conversa, não comando.
        slack: quanto o comando pode explicar o áudio pior que a transcrição livre.
            A transcrição livre é o melhor palpite do Whisper, então quase sempre tem
            a nota mais alta; o comando certo costuma ficar um pouco abaixo dela.
        margin: quanto o comando precisa ganhar da melhor frase de outra ação.
        floor: nota mínima; abaixo disso o áudio não se parece com comando nenhum.
    """

    max_words: int = 6
    slack: float = 1.0
    margin: float = 0.3
    floor: float = -2.5

    def applies_to(self, text: str) -> bool:
        words = text.split()
        return 0 < len(words) <= self.max_words

    def choose(self, free_score: float, scored: Sequence[Scored]) -> Scored | None:
        """O comando que o áudio diz, ou ``None`` se nenhum ganhou com folga."""
        if not scored:
            return None
        ranked = sorted(scored, key=lambda s: s.score, reverse=True)
        best = ranked[0]
        if best.score < self.floor or best.score < free_score - self.slack:
            return None
        rival = next((s for s in ranked[1:] if s.candidate.action != best.candidate.action), None)
        if rival is not None and best.score - rival.score < self.margin:
            return None
        return best
