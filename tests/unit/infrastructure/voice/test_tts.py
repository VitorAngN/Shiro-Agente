"""Kokoro em processo separado: protocolo, falhas na partida e reserva SAPI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shiro.config.settings import TTSSettings
from shiro.infrastructure.voice.tts import KokoroProcessTTS, TTSError, build_tts


def fake_worker(mode: str = "ok") -> list[str]:
    return [sys.executable, "-m", "tests.fakes.tts_worker", mode]


async def test_kokoro_process_protocol() -> None:
    tts = KokoroProcessTTS(
        model=Path("m"), voices=Path("v"), voice="pf_dora", command=fake_worker()
    )
    try:
        audio = await tts.synthesize("Olá")
        assert audio.rate == 24_000
        assert len(audio.samples) == 240 * 3
        assert tts.voices == ["pf_dora", "pm_alex"]
        assert tts.name == "kokoro/pf_dora"
        with pytest.raises(TTSError, match="texto ruim"):
            await tts.synthesize("falhe")
        again = await tts.synthesize("de novo")  # o processo continua vivo depois de um erro
        assert len(again.samples) == 240 * 7
    finally:
        await tts.aclose()
    await tts.aclose()  # fechar duas vezes não quebra


async def test_kokoro_startup_failures() -> None:
    broken = KokoroProcessTTS(
        model=Path("m"), voices=Path("v"), voice="pf_dora", command=fake_worker("broken")
    )
    with pytest.raises(TTSError, match="modelo corrompido"):
        await broken.synthesize("oi")

    wrong_voice = KokoroProcessTTS(
        model=Path("m"), voices=Path("v"), voice="xx_nada", command=fake_worker()
    )
    with pytest.raises(TTSError, match="xx_nada"):
        await wrong_voice.synthesize("oi")

    dies = KokoroProcessTTS(
        model=Path("m"), voices=Path("v"), voice="pf_dora", command=fake_worker("die")
    )
    with pytest.raises(TTSError, match="terminou"):
        await dies.synthesize("oi")
    await dies.aclose()


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o SAPI é o reserva")
def test_build_tts_without_kokoro_files_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(TTSError, match="shiro voice setup"):
        build_tts(TTSSettings(), tmp_path)
    with pytest.raises(TTSError, match="Windows"):
        build_tts(TTSSettings(engine="sapi"), tmp_path)
