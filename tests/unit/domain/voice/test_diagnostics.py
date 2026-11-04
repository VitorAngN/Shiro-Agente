"""Diagnóstico do microfone: portão de ruído e volume baixo, a partir da gravação."""

from __future__ import annotations

import numpy as np

from shiro.domain.voice.audio import Audio
from shiro.domain.voice.diagnostics import inspect_recording

RATE = 16_000


def speech(seconds: float, level: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_gate_zeroes_the_silence_and_jumps() -> None:
    gated = np.concatenate([np.zeros(int(0.3 * RATE), dtype=np.float32), speech(0.8, 0.3)])
    report = inspect_recording(Audio(gated, RATE))
    assert report.gated and not report.quiet
    assert "portão de ruído" in report.advice()[0]


def test_room_noise_before_speech_is_normal() -> None:
    rng = np.random.default_rng(1)
    noise = (0.003 * rng.standard_normal(int(0.3 * RATE))).astype(np.float32)
    report = inspect_recording(Audio(np.concatenate([noise, speech(0.8, 0.3)]), RATE))
    assert not report.gated and report.advice() == []


def test_quiet_microphone() -> None:
    rng = np.random.default_rng(2)
    noise = (0.0005 * rng.standard_normal(int(0.3 * RATE))).astype(np.float32)
    report = inspect_recording(Audio(np.concatenate([noise, speech(0.8, 0.02)]), RATE))
    assert report.quiet and not report.gated
    assert "baixo" in report.advice()[0]
    assert not inspect_recording(Audio(np.zeros(10, dtype=np.float32), RATE)).gated
