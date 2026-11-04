"""Diagnóstico do microfone a partir de uma gravação, sem aparelho nenhum.

Um microfone de verdade sempre capta algum ruído de sala. Se o trecho antes da
fala vem com amostras exatamente zeradas e o som salta de uma vez, há um
"portão de ruído" (noise gate) no caminho: no headset, no app dele, nos
aprimoramentos do Windows ou num mixer como o Voicemeeter. O portão abre
atrasado e corta a primeira sílaba ("pausa" vira "ausa"), e nenhum modelo de
transcrição recupera um som que não chegou.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shiro.domain.voice.audio import Audio

_FRAME_S = 0.032
_ZERO = 1 / 32768  # menor passo do áudio de 16 bits
_GATE_ZEROS = 0.8  # fração de amostras zeradas antes da fala
_GATE_JUMP = 100.0  # quanto o som sobe de um quadro para o outro no começo da fala
_QUIET_PEAK = 0.05  # pico de energia abaixo disso: microfone baixo


@dataclass(frozen=True)
class MicReport:
    zeros_before_speech: float
    onset_jump: float
    peak_rms: float

    @property
    def gated(self) -> bool:
        return self.zeros_before_speech >= _GATE_ZEROS and self.onset_jump >= _GATE_JUMP

    @property
    def quiet(self) -> bool:
        return self.peak_rms < _QUIET_PEAK

    def advice(self) -> list[str]:
        tips: list[str] = []
        if self.gated:
            tips.append(
                "o microfone zera o som até você falar alto (portão de ruído) e corta a primeira"
                " sílaba: desligue a supressão de ruído ou o gate do headset, dos aprimoramentos"
                " do Windows (mmsys.cpl) ou do Voicemeeter"
            )
        if self.quiet:
            tips.append("o microfone está baixo: suba o volume de entrada no Windows")
        return tips


def inspect_recording(audio: Audio) -> MicReport:
    samples = audio.samples.astype(np.float32)
    frame = max(1, round(_FRAME_S * audio.rate))
    count = len(samples) // frame
    if count < 2:
        return MicReport(0.0, 1.0, float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0)
    rms = np.sqrt(np.mean(samples[: count * frame].reshape(count, frame) ** 2, axis=1))
    peak = float(rms.max())
    onset = int(np.argmax(rms > 0.1 * peak)) if peak > 0 else 0
    before = samples[: onset * frame]
    zeros = float(np.mean(np.abs(before) < _ZERO)) if len(before) else 0.0
    jump = float(rms[onset] / (rms[onset - 1] + 1e-9)) if onset > 0 else 1.0
    return MicReport(zeros_before_speech=zeros, onset_jump=jump, peak_rms=peak)
