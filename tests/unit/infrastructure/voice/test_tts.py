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
        build_tts(TTSSettings(engine="kokoro"), tmp_path)
    with pytest.raises(TTSError, match="Windows"):
        build_tts(TTSSettings(engine="sapi"), tmp_path)


async def test_edge_voice_falls_back_to_the_local_one_and_retries_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np

    from shiro.domain.voice.audio import Audio
    from shiro.infrastructure.voice import edge
    from shiro.infrastructure.voice.edge import FallbackTTS

    class Voice:
        def __init__(self, name: str, fails: bool) -> None:
            self.name, self.fails, self.calls = name, fails, 0

        async def synthesize(self, text: str) -> Audio:
            self.calls += 1
            if self.fails:
                raise OSError("sem internet")
            return Audio(np.zeros(10, dtype=np.float32), 24_000)

        async def aclose(self) -> None:
            return None

    cloud, local = Voice("Microsoft", fails=True), Voice("Kokoro", fails=False)
    voice = FallbackTTS(cloud, local)
    clock = [100.0]
    monkeypatch.setattr(edge.time, "monotonic", lambda: clock[0])

    await voice.synthesize("oi")
    await voice.synthesize("oi de novo")
    assert (cloud.calls, local.calls) == (1, 2)  # não insiste na nuvem a cada frase
    cloud.fails = False
    clock[0] += 121
    await voice.synthesize("voltou")
    assert (cloud.calls, local.calls) == (2, 2)
    assert "reserva" in voice.name


def test_edge_settings_map_to_ssml_values() -> None:
    from shiro.infrastructure.voice.edge import EdgeTTS, _percent  # pyright: ignore[reportPrivateUsage]

    assert (_percent(1.0), _percent(1.2), _percent(0.85)) == ("+0%", "+20%", "-15%")
    assert EdgeTTS(voice="pt-BR-FranciscaNeural").name == "Microsoft pt-BR-FranciscaNeural"


def test_edge_engine_without_offline_backup(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("no Windows o SAPI é a reserva")
    tts, line = build_tts(TTSSettings(engine="edge"), tmp_path)
    assert "Francisca" in tts.name and "sem reserva" in line
