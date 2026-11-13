"""Comandos conhecidos na voz: corrige a transcrição quando ela quase acertou um comando.

``CommandCatalog`` lista as frases que o Tier 0 entende, escritas como o Whisper
escreve ("Abra o Steam."). ``CommandRescoringSTT`` envolve o Whisper (Decorator):
se a transcrição curta não vira comando, pede ao Whisper a nota de cada frase do
catálogo e troca o texto pelo comando que ganhar com folga (ADR-0021).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from shiro.domain.models import ToolCall
from shiro.domain.text import normalize
from shiro.domain.voice.audio import Audio
from shiro.domain.voice.ports import PhraseScorer, SpeechToText, Transcript
from shiro.domain.voice.rescoring import Candidate, RescoreRule, Scored

log = logging.getLogger(__name__)

_CALL_WORDS = 2  # "Shiro, ..." ou "Ei, Shiro, ..."

type Recognizer = Callable[[str], Sequence[ToolCall] | None]
"""O Tier 0 do roteador: as chamadas que o texto dispara, ou ``None``."""

# Duas formas de cada comando: o Whisper tem preferências de grafia, e a nota de
# uma frase cai se ela for escrita de um jeito que ele não usaria.
_APP_TEMPLATES = ("Abra o {}.", "Abre a {}.", "Feche o {}.", "Fecha a {}.")
_FIXED = (
    "Pausa a música.",
    "Pause a música.",
    "Continua a música.",
    "Toca a música.",
    "Próxima música.",
    "Pula essa música.",
    "Volta a música.",
    "Música anterior.",
    "Aumenta o volume.",
    "Sobe o volume.",
    "Abaixa o volume.",
    "Diminui o volume.",
    *(f"Volume em {level}." for level in range(10, 101, 10)),
    "Que horas são?",
    "Que dia é hoje?",
    "Como está o tempo?",
    "O que eu tenho hoje?",
    "O que eu tenho amanhã?",
    "O que eu tenho essa semana?",
    "Quais são minhas atividades?",
)


def action_of(calls: Sequence[ToolCall]) -> str:
    """Identidade da ação: frases diferentes que fazem a mesma coisa não competem."""
    return " + ".join(
        f"{call.name}({', '.join(f'{k}={v}' for k, v in sorted(call.arguments.items()))})"
        for call in calls
    )


class CommandCatalog:
    """As frases de comando que o roteador entende, cada uma com a sua ação."""

    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self._candidates = tuple(candidates)

    @classmethod
    def build(
        cls, recognize: Recognizer, apps: Sequence[str], extra: Sequence[str] = ()
    ) -> CommandCatalog:
        """Só entram as frases que o roteador de fato reconhece (``extra``: sites etc.)."""
        phrases = [template.format(app) for app in apps for template in _APP_TEMPLATES]
        phrases += extra
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for phrase in (*phrases, *_FIXED):
            calls = recognize(phrase)
            if calls and phrase not in seen:
                seen.add(phrase)
                candidates.append(Candidate(phrase, action_of(calls)))
        return cls(candidates)

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return self._candidates

    def addressed(self, prefix: str) -> tuple[Candidate, ...]:
        """As mesmas frases depois do chamado ("Ei, Shiro," + "abra o Steam.")."""
        return tuple(
            Candidate(f"{prefix} {c.phrase[0].lower()}{c.phrase[1:]}", c.action)
            for c in self._candidates
        )


@dataclass(frozen=True)
class Decision:
    """Notas de uma correção: a transcrição livre contra cada comando do catálogo."""

    heard: str
    free_score: float
    scored: tuple[Scored, ...]
    choice: Scored | None
    extra_ms: int

    def top(self, count: int = 3) -> list[Scored]:
        return sorted(self.scored, key=lambda s: s.score, reverse=True)[:count]


class CommandRescoringSTT:
    """Whisper que corrige comandos curtos mal transcritos (Decorator de ``SpeechToText``)."""

    def __init__(
        self,
        inner: SpeechToText,
        *,
        scorer: PhraseScorer,
        catalog: CommandCatalog,
        recognize: Recognizer,
        name: str,
        rule: RescoreRule | None = None,
    ) -> None:
        self._inner = inner
        self._scorer = scorer
        self._catalog = catalog
        self._recognize = recognize
        self._name = normalize(name)
        self._rule = rule or RescoreRule()
        self.last: Decision | None = None
        """A última decisão, para o ``shiro voice bench`` mostrar as notas."""

    @property
    def name(self) -> str:
        return f"{getattr(self._inner, 'name', 'stt')} + comandos"

    async def load(self) -> None:
        await self._inner.load()

    async def transcribe(self, audio: Audio) -> Transcript:
        heard = await self._inner.transcribe(audio)
        self.last = None
        text = heard.text
        if not self._catalog.candidates or not self._rule.applies_to(text):
            return heard
        if self._recognize(text):
            return heard
        started = time.perf_counter()
        candidates = self._candidates_for(text)
        scores = await self._scorer.score(audio, [text, *(c.phrase for c in candidates)])
        free_score, rest = scores[0], scores[1:]
        scored = [Scored(c, s) for c, s in zip(candidates, rest, strict=True)]
        choice = self._rule.choose(free_score, scored)
        extra_ms = round((time.perf_counter() - started) * 1000)
        self.last = Decision(text, free_score, tuple(scored), choice, extra_ms)
        latency = heard.latency_ms + extra_ms
        if choice is None:
            return Transcript(text=text, audio_s=heard.audio_s, latency_ms=latency)
        log.info("ouvi %r; entendi o comando %r", text, choice.candidate.phrase)
        return Transcript(
            text=choice.candidate.phrase, audio_s=heard.audio_s, latency_ms=latency, heard=text
        )

    def _candidates_for(self, text: str) -> tuple[Candidate, ...]:
        """Se a frase começa chamando a SHIRO, os comandos também começam assim."""
        words = text.split()
        for index, word in enumerate(words[:_CALL_WORDS]):
            if self._name and normalize(word) == self._name and index + 1 < len(words):
                return self._catalog.addressed(" ".join(words[: index + 1]))
        return self._catalog.candidates
