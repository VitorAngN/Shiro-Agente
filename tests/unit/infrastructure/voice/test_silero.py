"""Silero VAD de verdade, na CPU."""

from __future__ import annotations

import numpy as np
import pytest

from shiro.domain.voice.endpointing import FRAME
from shiro.infrastructure.voice.silero import SileroVAD


def test_silero_vad_runs_on_cpu() -> None:
    vad = SileroVAD()
    assert vad.probability(np.zeros(FRAME, dtype=np.float32)) < 0.2
    vad.reset()
    with pytest.raises(ValueError, match="512"):
        vad.probability(np.zeros(100, dtype=np.float32))
