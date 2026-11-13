"""Fala para texto com faster-whisper, na CPU em int8 (ADR-0004, ADR-0010).

O modelo é carregado uma vez e reaproveitado. A transcrição roda numa thread
para não travar o laço de eventos. Na primeira vez, o faster-whisper baixa o
modelo do Hugging Face para o cache do usuário.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np

from shiro.config.settings import STTSettings
from shiro.domain.voice.audio import STT_RATE, Audio
from shiro.domain.voice.ports import Transcript
from shiro.domain.voice.speech import clean_transcript

# Segmentos com muita chance de não ser fala e baixa confiança são descartados.
_NO_SPEECH = 0.6
_LOW_CONFIDENCE = -1.0

# Notas de frases (reconhecimento restrito de comandos, ADR-0021).
_SCORE_BATCH = 16  # frases por passada do decodificador; cada uma copia a saída do codificador
_MIN_PROB = 1e-10
_PROMPT_TOKENS = 223  # metade do contexto do decodificador, como o faster-whisper


class _Segment(Protocol):
    text: str
    no_speech_prob: float
    avg_logprob: float


type ModelFactory = Callable[[STTSettings, str], Any]


def _whisper(settings: STTSettings, source: str) -> Any:
    from faster_whisper import WhisperModel  # pyright: ignore[reportMissingTypeStubs]

    return WhisperModel(
        source,
        device=settings.device,
        compute_type=settings.compute_type,
        cpu_threads=settings.threads,
    )


def vocabulary_prompt(name: str, apps: Sequence[str], words: Sequence[str] = ()) -> str:
    """Prompt inicial em forma de comandos de exemplo, com os nomes que o Whisper erraria.

    Frases completas puxam mais o Whisper que uma lista solta: ele tende a
    continuar no mesmo estilo e com a mesma grafia.
    """
    commands = [f"Abra o {app}." for app in apps[:8]]
    terms = list(dict.fromkeys(words))[:10]
    sites = [f"Pesquisa no {terms[0]}.", f"Abre o {', o '.join(terms[1:])}."] if terms else []
    return " ".join(
        [
            f"{name}, que horas são?",
            *commands,
            *sites,
            "Volume em 30.",
            "Me lembra da prova às 18h.",
        ]
    )


def vocabulary_hotwords(name: str, apps: Sequence[str], words: Sequence[str] = ()) -> str:
    """Palavras que o Whisper deve preferir quando o som for parecido (``hotwords``).

    Nomes em inglês (YouTube, Chrome, Steam) são os que o Whisper em português mais erra.
    """
    return " ".join(dict.fromkeys([name, *apps[:12], *words[:16]]))


def score_tokens(
    whisper: Any,
    encoded: np.ndarray,
    start: Sequence[int],
    texts: Sequence[Sequence[int]],
    frames: int,
    *,
    batch: int = _SCORE_BATCH,
) -> list[float]:
    """Média do log da probabilidade de cada sequência de tokens, dado o áudio codificado.

    ``whisper`` é o ``ctranslate2.models.Whisper``; ``encoded`` é a saída do
    codificador para um trecho (``[1, quadros, dimensão]``). O codificador, a parte
    cara, roda uma vez só: a saída é repetida para cada frase e só o decodificador
    trabalha em lote, forçado a seguir cada frase (``align``).
    """
    import ctranslate2  # pyright: ignore[reportMissingTypeStubs]

    scores: list[float] = []
    for first in range(0, len(texts), batch):
        chunk = [list(tokens) for tokens in texts[first : first + batch]]
        tiled = ctranslate2.StorageView.from_array(np.repeat(encoded, len(chunk), axis=0))
        results = whisper.align(tiled, list(start), chunk, frames)
        for result in results:
            probs: list[float] = list(result.text_token_probs)
            logs = [math.log(max(p, _MIN_PROB)) for p in probs]
            scores.append(sum(logs) / len(logs) if logs else -math.inf)
    return scores


class FasterWhisperSTT:
    def __init__(
        self,
        settings: STTSettings,
        *,
        source: str | None = None,
        prompt: str = "",
        hotwords: str = "",
        factory: ModelFactory = _whisper,
    ) -> None:
        """``source``: pasta do modelo já baixado; sem ela, usa o nome em ``settings.model``."""
        self._settings = settings
        self._source = source or settings.model
        self._prompt = prompt or None
        self._hotwords = hotwords or None
        self._factory = factory
        self._model: Any = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return f"faster-whisper/{self._settings.model}"

    async def load(self) -> None:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._factory, self._settings, self._source)

    async def transcribe(self, audio: Audio) -> Transcript:
        await self.load()
        clip = audio.resampled(STT_RATE)
        started = time.perf_counter()
        text = await asyncio.to_thread(self._run, clip)
        latency = round((time.perf_counter() - started) * 1000)
        return Transcript(text=text, audio_s=clip.duration, latency_ms=latency)

    def _run(self, clip: Audio) -> str:
        segments, _info = self._model.transcribe(
            clip.samples,
            language=self._settings.language,
            beam_size=self._settings.beam_size,
            vad_filter=False,  # o VAD já recortou a frase
            condition_on_previous_text=False,
            without_timestamps=True,
            initial_prompt=self._prompt,
            hotwords=self._hotwords,
        )
        kept: list[str] = []
        for segment in segments:
            seg: _Segment = segment
            if seg.no_speech_prob > _NO_SPEECH and seg.avg_logprob < _LOW_CONFIDENCE:
                continue
            kept.append(seg.text.strip())
        return clean_transcript(" ".join(kept))

    async def score(self, audio: Audio, phrases: Sequence[str]) -> list[float]:
        """Quanto cada frase explica o áudio (``PhraseScorer``), com o prompt da transcrição."""
        if not phrases:
            return []
        await self.load()
        clip = audio.resampled(STT_RATE)
        return await asyncio.to_thread(self._score, clip, list(phrases))

    def _score(self, clip: Audio, phrases: list[str]) -> list[float]:
        from faster_whisper.audio import pad_or_trim  # pyright: ignore[reportMissingTypeStubs]
        from faster_whisper.tokenizer import Tokenizer  # pyright: ignore[reportMissingTypeStubs]

        model = self._model
        tokenizer: Any = Tokenizer(
            model.hf_tokenizer,
            model.model.is_multilingual,
            task="transcribe",
            language=self._settings.language,
        )
        features = model.feature_extractor(clip.samples)
        frames = min(features.shape[-1] - 1, model.feature_extractor.nb_max_frames)
        segment = pad_or_trim(features[:, :frames])
        encoded = np.asarray(
            model.model.encode(_storage(segment[np.newaxis]), to_cpu=model.model.device == "cuda")
        )
        texts = [[*tokenizer.encode(" " + phrase.strip()), tokenizer.eot] for phrase in phrases]
        return score_tokens(model.model, encoded, self._start_sequence(tokenizer), texts, frames)

    def _start_sequence(self, tokenizer: Any) -> list[int]:
        """O começo que o decodificador vê na transcrição: vocabulário, depois o início."""
        context: list[int] = []
        if self._hotwords:
            context += tokenizer.encode(" " + self._hotwords.strip())[:_PROMPT_TOKENS]
        if self._prompt:
            context += tokenizer.encode(" " + self._prompt.strip())[-_PROMPT_TOKENS:]
        start = [tokenizer.sot_prev, *context] if context else []
        return [*start, *tokenizer.sot_sequence, tokenizer.no_timestamps]


def _storage(array: np.ndarray) -> Any:
    import ctranslate2  # pyright: ignore[reportMissingTypeStubs]

    return ctranslate2.StorageView.from_array(np.ascontiguousarray(array, dtype=np.float32))
