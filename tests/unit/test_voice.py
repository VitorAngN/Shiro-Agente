"""Voz (marco 1b): áudio, texto falado, detecção de fala, Whisper, Kokoro e atalhos."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest

from shiro.settings import STTSettings, TTSSettings
from shiro.voice import models
from shiro.voice.audio import STT_RATE, Audio, Cues, Samples, concat, tone
from shiro.voice.hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, HotkeyError, parse_hotkey
from shiro.voice.speech import clean_transcript, for_speech, sentences, yes_or_no
from shiro.voice.stt import FasterWhisperSTT, vocabulary_prompt
from shiro.voice.tts import KokoroProcessTTS, TTSError, build_tts
from shiro.voice.vad import (
    FRAME,
    EndpointConfig,
    Endpointer,
    ListenControl,
    SileroVAD,
    Status,
    record_utterance,
)

# ---------------------------------------------------------------------- áudio


def test_wav_round_trip_and_resampling() -> None:
    clip = tone(440, 500, rate=24_000, volume=0.5)
    back = Audio.from_wav(clip.to_wav())
    assert back.rate == 24_000
    assert np.allclose(back.samples, clip.samples, atol=1e-4)
    assert clip.duration == pytest.approx(0.5)
    resampled = clip.resampled(STT_RATE)
    assert len(resampled.samples) == 8000
    assert resampled.resampled(STT_RATE) is not None
    assert Audio.empty().resampled(8000).duration == 0


def test_stereo_pcm_becomes_mono_and_cues_can_be_silenced() -> None:
    stereo = np.array([1000, 3000, -2000, -4000], dtype="<i2").tobytes()
    mono = Audio.from_pcm16(stereo, 8000, channels=2)
    assert np.allclose(mono.samples, [2000 / 32768, -3000 / 32768])
    quiet = Cues.generate(0)
    assert quiet.listening.duration == 0
    loud = Cues.generate(0.2)
    assert 0.15 < loud.listening.duration < 0.3
    assert float(np.abs(loud.listening.samples).max()) <= 0.2 + 1e-6
    assert concat([], 16000).duration == 0


def test_tone_has_no_click_at_the_edges() -> None:
    beep = tone(1000, 100, rate=16_000, volume=1.0)
    assert abs(float(beep.samples[0])) < 1e-3
    assert abs(float(beep.samples[-1])) < 0.01
    assert float(np.abs(beep.samples).max()) > 0.9


# ---------------------------------------------------------------------- texto falado


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("Anotado: prova, sexta, às 23h59.", "Anotado: prova, sexta, às 23 e 59."),
        ("Te lembro às 8h.", "Te lembro às 8 horas."),
        ("Às 1h da manhã.", "Às 1 hora da manhã."),
        ("Volume em 20%.", "Volume em 20 por cento."),
        ("Faz 21 °C em Curitiba.", "Faz 21 graus em Curitiba."),
        ("Custa R$ 10,50.", "Custa 10,50 reais."),
        ("**Pronto**: `ok`", "Pronto : ok"),
        ("Veja https://exemplo.com/x agora.", "Veja o link na tela agora."),
    ],
)
def test_for_speech(written: str, spoken: str) -> None:
    assert for_speech(written) == spoken


def test_sentences_keep_short_ones_together() -> None:
    assert sentences("Anotado: trabalho de cálculo, sexta. Te aviso um dia antes. Ok.") == [
        "Anotado: trabalho de cálculo, sexta.",
        "Te aviso um dia antes. Ok.",
    ]
    assert sentences("") == []
    assert sentences("Oi. Tudo certo por aqui, e com você?") == [
        "Oi. Tudo certo por aqui, e com você?"
    ]


@pytest.mark.parametrize(
    ("heard", "kept"),
    [
        ("Legendas pela comunidade Amara.org", ""),
        ("Obrigado.", ""),
        ("  ", ""),
        ("Obrigado por assistir!", ""),
        ("Abre o Spotify.", "Abre o Spotify."),
        ("obrigado pela ajuda", "obrigado pela ajuda"),
    ],
)
def test_clean_transcript_drops_known_hallucinations(heard: str, kept: str) -> None:
    assert clean_transcript(heard) == kept


@pytest.mark.parametrize(
    ("heard", "answer"),
    [
        ("Sim.", True),
        ("Pode sim, Shiro", True),
        ("Shiro, confirmo", True),
        ("Manda ver!", True),
        ("Não.", False),
        ("Não, deixa pra lá", False),
        ("Cancela", False),
        ("Melhor não", False),
        ("Talvez depois", None),
        ("Qual volume?", None),
    ],
)
def test_yes_or_no(heard: str, answer: bool | None) -> None:
    assert yes_or_no(heard) is answer


# ---------------------------------------------------------------------- detecção de fala


def frames(count: int, value: float = 0.0) -> list[Samples]:
    return [np.full(FRAME, value, dtype=np.float32) for _ in range(count)]


def push_all(endpointer: Endpointer, probabilities: list[float]) -> Status:
    status = endpointer.status
    for index, probability in enumerate(probabilities):
        status = endpointer.push(np.full(FRAME, index, dtype=np.float32), probability)
    return status


def test_endpointer_detects_start_and_end_with_pre_roll() -> None:
    config = EndpointConfig(end_silence_ms=320, pre_roll_ms=64, start_frames=3)
    endpointer = Endpointer(config)
    # 5 quadros de silêncio, 20 de fala, 12 de silêncio (384 ms > 320 ms)
    status = push_all(endpointer, [0.0] * 5 + [0.9] * 20 + [0.0] * 12)

    assert status is Status.DONE
    audio = endpointer.audio()
    first = int(audio.samples[0])
    assert first == 3  # 2 quadros de pré-escuta antes dos 3 que confirmaram a fala
    # termina com só 3 quadros de silêncio depois da fala
    assert int(audio.samples[-1]) == 5 + 20 + 2


def test_short_pauses_do_not_end_the_phrase() -> None:
    endpointer = Endpointer(EndpointConfig(end_silence_ms=320))
    pattern = [0.9] * 5 + ([0.1] * 6 + [0.9] * 3) * 4  # pausas de 192 ms
    assert push_all(endpointer, pattern) is Status.SPEAKING
    # 0.4 está na histerese (limiar 0.5 - 0.15 = 0.35): não conta como silêncio
    assert push_all(endpointer, [0.4] * 30) is Status.SPEAKING


def test_no_speech_times_out_and_long_speech_is_cut() -> None:
    quiet = Endpointer(EndpointConfig(start_timeout_s=1.0))
    assert push_all(quiet, [0.2] * 40) is Status.NO_SPEECH  # 40 x 32 ms > 1 s
    assert quiet.push(np.zeros(FRAME, dtype=np.float32), 0.9) is Status.NO_SPEECH

    chatty = Endpointer(EndpointConfig(max_utterance_s=2.0))
    assert push_all(chatty, [0.9] * 80) is Status.DONE
    assert chatty.audio().duration <= 2.2


class FakeMic:
    def __init__(self, blocks: list[Samples]) -> None:
        self.blocks = blocks

    @contextlib.asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
        async def generate() -> AsyncIterator[Samples]:
            for block in self.blocks:
                await asyncio.sleep(0)
                yield block

        yield generate()


class ScriptedDetector:
    """Probabilidade = valor do primeiro elemento do quadro (os testes escrevem ali)."""

    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def probability(self, frame: Samples) -> float:
        return float(frame[0])


async def test_record_utterance_finish_and_cancel() -> None:
    speech = frames(5) + frames(10, 0.9) + frames(30)
    detector = ScriptedDetector()
    audio = await record_utterance(FakeMic(speech), detector, EndpointConfig(end_silence_ms=320))
    assert audio is not None and audio.duration > 0.3
    assert detector.resets == 1

    assert await record_utterance(FakeMic(frames(10)), detector, EndpointConfig()) is None

    control = ListenControl()
    early = ListenControl()
    early.finish.set()  # tocar de novo antes de falar: nada a transcrever
    assert await record_utterance(FakeMic(frames(5)), detector, EndpointConfig(), early) is None

    class FinishMidway(FakeMic):
        @contextlib.asynccontextmanager
        async def open(self) -> AsyncIterator[AsyncIterator[Samples]]:
            async def generate() -> AsyncIterator[Samples]:
                for index, block in enumerate(self.blocks):
                    if index == 10:
                        control.finish.set()  # segundo toque com a fala em andamento
                    await asyncio.sleep(0)
                    yield block

            yield generate()

    finished = await record_utterance(
        FinishMidway(frames(200, 0.9)), detector, EndpointConfig(), control
    )
    assert finished is not None
    assert finished.duration < 0.5  # parou no toque, não no limite de 15 s

    cancelled = ListenControl()
    cancelled.cancel.set()
    assert (
        await record_utterance(FakeMic(frames(5, 0.9)), detector, EndpointConfig(), cancelled)
        is None
    )


def test_silero_vad_runs_on_cpu() -> None:
    vad = SileroVAD()
    assert vad.probability(np.zeros(FRAME, dtype=np.float32)) < 0.2
    vad.reset()
    with pytest.raises(ValueError, match="512"):
        vad.probability(np.zeros(100, dtype=np.float32))


# ---------------------------------------------------------------------- atalhos


def test_parse_hotkey() -> None:
    talk = parse_hotkey("ctrl+alt+space")
    assert (talk.modifiers, talk.key) == (MOD_CONTROL | MOD_ALT, 0x20)
    stop = parse_hotkey("Ctrl + Alt + Shift + S")
    assert (stop.modifiers, stop.key) == (MOD_CONTROL | MOD_ALT | MOD_SHIFT, ord("S"))
    assert parse_hotkey("alt+f9").key == 0x78
    for bad in ("", "space", "ctrl+hyper+x", "ctrl+çç"):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)


# ---------------------------------------------------------------------- Whisper


class FakeWhisper:
    def __init__(self, segments: list[SimpleNamespace]) -> None:
        self.segments = segments
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, samples: Samples, **options: Any) -> tuple[list[SimpleNamespace], None]:
        self.calls.append({"samples": len(samples), **options})
        return self.segments, None


def segment(text: str, no_speech: float = 0.1, logprob: float = -0.3) -> SimpleNamespace:
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


async def test_whisper_filters_noise_and_loads_once() -> None:
    model = FakeWhisper([segment(" Abre o"), segment(" Spotify."), segment(" la", 0.9, -1.5)])
    created: list[str] = []

    def factory(settings: STTSettings, source: str) -> FakeWhisper:
        created.append(source)
        return model

    stt = FasterWhisperSTT(
        STTSettings(model="base"), source="/modelos/base", prompt="Shiro.", factory=factory
    )
    clip = tone(300, 1000, rate=24_000)
    first = await stt.transcribe(clip)
    await stt.transcribe(clip)

    assert first.text == "Abre o Spotify."
    assert first.audio_s == pytest.approx(1.0)
    assert created == ["/modelos/base"]
    call = model.calls[0]
    assert call["samples"] == 16_000  # reamostrado para 16 kHz
    assert (call["language"], call["beam_size"], call["initial_prompt"]) == ("pt", 1, "Shiro.")
    assert stt.name == "faster-whisper/base"

    silent = FasterWhisperSTT(
        STTSettings(), factory=lambda _, __: FakeWhisper([segment("Obrigado.")])
    )
    assert (await silent.transcribe(clip)).text == ""


def test_vocabulary_prompt_names_the_assistant_and_apps() -> None:
    prompt = vocabulary_prompt("Shiro", ["Spotify", "VS Code"])
    assert prompt.startswith("Shiro, abre o Spotify.")
    assert "VS Code" in prompt
    assert vocabulary_prompt("Shiro", []).startswith("Shiro.")


# ---------------------------------------------------------------------- Kokoro


def fake_worker(mode: str = "ok") -> list[str]:
    return [sys.executable, "-m", "tests.fake_tts_worker", mode]


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


async def test_download_checks_known_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"modelo de teste" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    seen: list[int] = []
    sha = await models.download(
        client, "https://x/a.onnx", tmp_path / "a.onnx", lambda _, done, __: seen.append(done)
    )
    assert (tmp_path / "a.onnx").read_bytes() == payload
    assert seen[-1] == len(payload)

    monkeypatch.setitem(models.KNOWN_SHA256, "b.onnx", "0" * 64)
    with pytest.raises(models.DownloadError, match="hash"):
        await models.download(client, "https://x/b.onnx", tmp_path / "b.onnx")
    assert not (tmp_path / "b.onnx").exists()
    assert not (tmp_path / "b.onnx.part").exists()

    monkeypatch.setitem(models.KNOWN_SHA256, "c.onnx", sha)
    files = models.kokoro_files(tmp_path, "int8")
    assert not files.present
    monkeypatch.setitem(models.KNOWN_SHA256, files.model.name, sha)
    monkeypatch.setitem(models.KNOWN_SHA256, files.voices.name, sha)
    await models.ensure_kokoro(client, tmp_path, "int8")
    assert models.kokoro_files(tmp_path, "int8").present

    missing = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(models.DownloadError, match="404"):
        await models.download(missing, "https://x/d.onnx", tmp_path / "d.onnx")
    await client.aclose()
    await missing.aclose()


async def test_whisper_download_verifies_every_file(tmp_path: Path) -> None:
    import hashlib

    files = {"config.json": b'{"a": 1}', "vocabulary.txt": b"oi\n", "model.bin": b"\x00" * 4096}

    def blob(content: bytes) -> str:
        header = f"blob {len(content)}\0".encode()
        return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()

    tree = [
        {"type": "file", "path": ".gitattributes", "size": 1, "oid": "x"},
        {"type": "file", "path": "config.json", "size": 8, "oid": blob(files["config.json"])},
        {"type": "file", "path": "vocabulary.txt", "size": 3, "oid": blob(files["vocabulary.txt"])},
        {
            "type": "file",
            "path": "model.bin",
            "size": 4096,
            "lfs": {"oid": hashlib.sha256(files["model.bin"]).hexdigest()},
        },
    ]
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if "/api/models/" in request.url.path:
            return httpx.Response(200, json=tree)
        return httpx.Response(200, content=files[request.url.path.rsplit("/", 1)[-1]])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    folder = await models.ensure_whisper(client, tmp_path, "small")

    assert folder.name == "Systran--faster-whisper-small"
    assert (folder / "model.bin").read_bytes() == files["model.bin"]
    assert not (folder / ".gitattributes").exists()
    assert models.whisper_ready(tmp_path, "small")
    count = len(requests)
    assert await models.ensure_whisper(client, tmp_path, "small") == folder
    assert len(requests) == count  # pronto: não consulta de novo

    files["vocabulary.txt"] = b"adulterado"
    with pytest.raises(models.DownloadError, match="hash"):
        await models.ensure_whisper(client, tmp_path / "outro", "base")
    assert models.whisper_repo("org/modelo") == "org/modelo"

    missing = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(models.DownloadError, match="404"):
        await models.ensure_whisper(missing, tmp_path / "x", "nada")
    empty = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])))
    with pytest.raises(models.DownloadError, match="faster-whisper"):
        await models.ensure_whisper(empty, tmp_path / "y", "outra")
    for c in (client, missing, empty):
        await c.aclose()
