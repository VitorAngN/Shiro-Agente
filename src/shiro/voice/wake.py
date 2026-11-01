"""Palavra de ativação: "Ei, Shiro" (ADR-0016).

Dois motores, escolhidos em ``voice.wake_word.engine``:

* ``whisper``: o VAD recorta cada frase falada perto do PC; um Whisper pequeno
  confere se ela começa com o nome. Funciona com o nome de verdade, sem treino,
  e entende a frase inteira de uma vez ("Ei Shiro, abre o Spotify"). Gasta mais
  CPU quando há muita conversa por perto.
* ``openwakeword``: detector leve e contínuo (~5% de um núcleo). Precisa de um
  modelo treinado para "Ei, Shiro"; até lá, os modelos embutidos (``hey_jarvis``)
  servem para testar.

Enquanto a SHIRO ouve, pensa ou fala, o detector fica em pausa: ela não se
ativa com a própria voz.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

import numpy as np

from shiro.core.text import normalize
from shiro.voice.oww import CHUNK, OpenWakeWord
from shiro.voice.ports import Microphone, SpeechDetector, SpeechToText
from shiro.voice.vad import EndpointConfig, Endpointer, Status

# Como o Whisper escreve o chamado: "Ei, Shiro", "Aishiro", "Aiciro", "Eishiro", "A. Shiro".
_NAME = r"(?:shiro|xiro|chiro|shiru|xiru|shirou|shirow)"
_GREETING = r"(?:ei|ai|hei|hey|oi|ok|okay)"
_WAKE = re.compile(
    r"^(?:(?:hum|hm|ah|eh|ahn)\s*,?\s*)?"
    rf"(?:(?:{_GREETING}|e|a)(?:{_NAME}|ciro)"  # grudado: "aishiro", "aiciro"
    rf"|(?:{_GREETING}\s*,?\s*)?{_NAME}"  # "ei, shiro" ou só "shiro"
    # "e shiro," / "a shiro.": artigo só vale como chamado (vírgula ou fim depois do nome),
    # para "a Shiro é legal" numa conversa não acordá-la.
    rf"|(?:e|a)\s*,?\s*{_NAME}(?=\s*(?:,|$)))"
    r"\b\s*,?\s*(?P<rest>.*)$"
)


def _plain(text: str) -> str:
    """Minúsculas sem acento; pontuação de fim vira vírgula, para marcar o vocativo."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    plain = re.sub(r"[.!?;:…]+", ",", plain)
    plain = re.sub(r"[^a-z0-9, ]", " ", plain)
    plain = re.sub(r"\s*,\s*", ", ", plain)
    return re.sub(r"\s+", " ", plain).strip(" ,")


def wake_match(text: str, phrases: Sequence[str]) -> str | None:
    """Resto do pedido depois da palavra de ativação, ``""`` se só chamou, ou ``None``.

    >>> wake_match("Ei, Shiro, abre o Spotify.", ["ei shiro", "shiro"])
    'abre o spotify'
    """
    plain = _plain(text)
    if match := _WAKE.match(plain):
        return normalize(match["rest"].replace(",", " ")).strip()
    # Frases configuradas pelo usuário (outro nome, outra saudação).
    flat = normalize(plain.replace(",", " "))
    for phrase in sorted((normalize(p) for p in phrases), key=len, reverse=True):
        if flat == phrase:
            return ""
        if flat.startswith(phrase + " "):
            return flat[len(phrase) + 1 :].strip()
    return None


def strip_wake(text: str, phrases: Sequence[str]) -> str:
    """Tira a palavra de ativação do começo, preservando acentos e maiúsculas do resto."""
    words = text.split()
    for size in range(min(len(words), 4), 0, -1):
        if wake_match(" ".join(words[:size]), phrases) == "":
            return " ".join(words[size:]).lstrip(",.!? ").strip()
    return text.strip()


class WakeEvents(Protocol):
    def wake(self) -> None:
        """Só chamou ("Ei, Shiro"): começar a ouvir o pedido."""
        ...

    def command(self, text: str) -> None:
        """Chamou e já pediu ("Ei Shiro, abre o Spotify")."""
        ...


class WakeListener:
    """Escuta contínua do microfone, em pausa enquanto a SHIRO não está livre."""

    def __init__(
        self,
        *,
        microphone: Microphone,
        events: WakeEvents,
        is_idle: Callable[[], bool],
        cooldown_s: float = 1.5,
    ) -> None:
        self._microphone = microphone
        self._events = events
        self._is_idle = is_idle
        self._cooldown_s = cooldown_s
        self._quiet_until = 0.0
        self.enabled = True

    def _ready(self) -> bool:
        return self.enabled and self._is_idle() and time.monotonic() >= self._quiet_until

    def _fired(self) -> None:
        self._quiet_until = time.monotonic() + self._cooldown_s

    async def run_openwakeword(self, detector: OpenWakeWord, threshold: float) -> None:
        pending = np.zeros(0, dtype=np.float32)
        async with self._microphone.open() as frames:
            async for frame in frames:
                pending = np.concatenate([pending, frame])
                while len(pending) >= CHUNK:
                    block, pending = pending[:CHUNK], pending[CHUNK:]
                    pcm = (np.clip(block, -1.0, 1.0) * 32767).astype(np.int16)
                    score = detector.score(pcm)
                    if not self._ready():
                        continue
                    if score >= threshold:
                        self._fired()
                        detector.reset()
                        self._events.wake()

    async def run_whisper(
        self,
        *,
        vad: SpeechDetector,
        check: SpeechToText,
        full: SpeechToText,
        phrases: Sequence[str],
        listen: EndpointConfig,
        max_phrase_s: float,
    ) -> None:
        config = replace(
            listen, start_timeout_s=3600, end_silence_ms=min(listen.end_silence_ms, 600)
        )
        endpointer = Endpointer(config)
        vad.reset()
        async with self._microphone.open() as frames:
            async for frame in frames:
                status = endpointer.push(frame, vad.probability(frame))
                if status is Status.SPEAKING or status is Status.WAITING:
                    continue
                audio = endpointer.audio() if status is Status.DONE else None
                endpointer = Endpointer(config)
                vad.reset()
                if audio is None or not self._ready() or audio.duration > max_phrase_s:
                    continue
                heard = (await check.transcribe(audio)).text
                rest = wake_match(heard, phrases)
                if rest is None or not self._ready():
                    continue
                self._fired()
                if not rest:
                    self._events.wake()
                    continue
                # O pedido veio junto: transcreve de novo com o modelo principal, mais preciso.
                precise = strip_wake((await full.transcribe(audio)).text, phrases)
                self._events.command(precise or rest)
