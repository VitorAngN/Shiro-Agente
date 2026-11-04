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

import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

import numpy as np

from shiro.domain.voice.endpointing import EndpointConfig, Endpointer, Status
from shiro.domain.voice.ports import Microphone, SpeechDetector, SpeechToText
from shiro.domain.voice.wake_phrase import strip_wake, wake_match
from shiro.infrastructure.voice.oww import CHUNK, OpenWakeWord


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
