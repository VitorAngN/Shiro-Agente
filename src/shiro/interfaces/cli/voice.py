"""Comandos de voz: ``shiro voice`` e subcomandos (marco 1b).

* ``shiro voice``: conversa por voz (atalho global, Enter ou texto digitado);
* ``shiro voice devices``: lista microfones e saídas de áudio;
* ``shiro voice say "texto"``: fala, ou salva em WAV com ``--out``;
* ``shiro voice listen``: ouve uma frase e mostra a transcrição;
* ``shiro voice setup``: baixa os modelos (Whisper e Kokoro);
* ``shiro voice bench``: mede a voz sem tocar nada (texto → fala → texto).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from shiro import __version__
from shiro.config import paths
from shiro.config.settings import Settings
from shiro.interfaces.voice.runtime import endpoint_for, print_progress, tts_for, whisper_for


def add_voice_parser(commands: Any) -> None:
    voice = commands.add_parser("voice", help="conversa com a SHIRO por voz")
    voice.add_argument("-v", "--verbose", action="store_true", help="mostra tempos e ferramentas")
    voice.add_argument("--no-warmup", action="store_true", help="não pré-carrega o modelo local")
    actions = voice.add_subparsers(dest="voice_command", metavar="ação")
    actions.add_parser("devices", help="lista microfones e saídas de áudio")
    say = actions.add_parser("say", help="fala um texto (ou salva em WAV)")
    say.add_argument("text")
    say.add_argument("--out", type=Path, help="salva em WAV em vez de tocar")
    say.add_argument("--engine", choices=("kokoro", "sapi"), help="motor de voz")
    actions.add_parser("listen", help="ouve uma frase e mostra a transcrição")
    record = actions.add_parser(
        "record", help="grava você dizendo comandos, para medir o Whisper (fica só no PC)"
    )
    record.add_argument("--count", type=int, help="quantas frases gravar (padrão: todas)")
    actions.add_parser("setup", help="baixa e prepara os modelos de voz")
    bench = actions.add_parser("bench", help="mede fala e transcrição sem tocar áudio")
    bench.add_argument("--engine", nargs="*", choices=("kokoro", "sapi"), help="motores de voz")
    bench.add_argument("--stt", nargs="*", help="modelos do Whisper (ex.: base small)")
    bench.add_argument("--out", type=Path, help="salva o relatório em JSON")
    bench.add_argument(
        "--samples",
        nargs="?",
        const="latest",
        help="usa as suas gravações (shiro voice record) em vez da voz sintetizada",
    )
    bench.add_argument(
        "--hotwords", choices=("on", "off", "both"), default="on", help="compara com e sem hotwords"
    )
    bench.add_argument("--device", nargs="*", choices=("cpu", "cuda"), help="onde rodar o Whisper")
    bench.add_argument(
        "--wake", action="store_true", help='mede a palavra de ativação ("Ei, Shiro")'
    )


def run_voice(settings: Settings, args: argparse.Namespace) -> int:
    command = args.voice_command
    if command == "devices":
        return _devices()
    handlers = {
        None: _session,
        "say": _say,
        "listen": _listen,
        "record": _record,
        "setup": _setup,
        "bench": _bench,
    }
    try:
        return asyncio.run(handlers[command](settings, args))
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------- utilidades


# Reexportados para os testes poderem trocar por dublês.
_tts = tts_for
_ready_stt = whisper_for
_endpoint = endpoint_for
_progress = print_progress


def _seconds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " s"


# ---------------------------------------------------------------------- sessão


async def _session(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.infrastructure.observability.logging import (
        configure_logging,
        log_lifecycle,
        watch_event_loop,
    )
    from shiro.infrastructure.system.singleton import AlreadyRunningError, single_instance
    from shiro.infrastructure.voice.devices import AudioDeviceError
    from shiro.infrastructure.voice.models import DownloadError
    from shiro.infrastructure.voice.tts import TTSError
    from shiro.interfaces.text.session import CliConfirmation, use_safe_output
    from shiro.interfaces.text.theme import Theme
    from shiro.interfaces.voice.runtime import build_voice_runtime

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=False)
    log_lifecycle("voice")
    watch_event_loop()
    theme = Theme.for_stream(sys.stdout)
    try:
        lock = single_instance()
    except AlreadyRunningError as exc:
        print(theme.status(False, str(exc)))
        return 1
    try:
        runtime = await build_voice_runtime(
            settings, keyboard=CliConfirmation(theme=theme), verbose=args.verbose, theme=theme
        )
    except (TTSError, DownloadError, AudioDeviceError, OSError) as exc:
        print(theme.status(False, str(exc)))
        lock.release()
        return 1
    session = runtime.session
    try:
        session.print(theme.banner(__version__))
        await runtime.start(
            lambda ok, text: session.print(theme.status(ok, text)), warmup=not args.no_warmup
        )
        session.print("")
        hint = f"{runtime.talk_hint} (ou Enter)" if runtime.talk_hint != "Enter" else "Enter"
        session.print(
            theme.meta(f"{hint}: falar · digitar: mandar texto · p: parar · sair: encerrar")
        )
        runtime.triggers.add_terminal(input)
        await session.run(runtime.triggers)
    except (AudioDeviceError, TTSError) as exc:
        session.print(theme.status(False, str(exc)))
        return 1
    finally:
        await runtime.aclose()
        lock.release()
    return 0


# ---------------------------------------------------------------------- utilitários


def _devices() -> int:
    from shiro.infrastructure.voice.devices import AudioDeviceError, list_devices

    try:
        devices = list_devices()
    except AudioDeviceError as exc:
        print(f"✗ {exc}")
        return 1
    for kind, attribute in (("Microfones", "inputs"), ("Saídas", "outputs")):
        print(f"{kind}:")
        seen: set[str] = set()
        for device in devices:
            if getattr(device, attribute) <= 0 or (
                device.hostapi != "MME" and sys.platform == "win32"
            ):
                continue
            if device.name in seen:
                continue
            seen.add(device.name)
            default = device.is_default_input if attribute == "inputs" else device.is_default_output
            mark = "  ← padrão" if default else ""
            print(f"  {device.name}{mark}")
    print("\nPara escolher, ponha parte do nome em voice.input_device ou voice.output_device.")
    return 0


async def _say(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.domain.voice.speech import for_speech
    from shiro.infrastructure.voice.devices import SoundDevicePlayer
    from shiro.infrastructure.voice.tts import TTSError

    try:
        tts, status = _tts(settings, args.engine)
    except TTSError as exc:
        print(f"✗ {exc}")
        return 1
    try:
        started = time.perf_counter()
        audio = await tts.synthesize(for_speech(args.text))
        elapsed = time.perf_counter() - started
    except TTSError as exc:
        print(f"✗ {exc}")
        return 1
    finally:
        await tts.aclose()
    print(f"{status}: {_seconds(audio.duration)} de fala em {_seconds(elapsed)}")
    if args.out:
        args.out.write_bytes(audio.to_wav())
        print(f"salvo em {args.out}")
        return 0
    await SoundDevicePlayer(settings.voice.output_device).play(
        audio.scaled(settings.voice.tts.volume)
    )
    return 0


async def _listen(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.application.voice.listening import record_utterance
    from shiro.domain.voice.audio import Cues
    from shiro.infrastructure.voice.devices import SoundDeviceMicrophone, SoundDevicePlayer
    from shiro.infrastructure.voice.silero import SileroVAD

    stt = await _ready_stt(settings)
    await stt.load()
    player = SoundDevicePlayer(settings.voice.output_device)
    cues = Cues.generate(settings.voice.cue_volume)
    print("fale depois do bipe…")
    await player.play(cues.listening)
    audio = await record_utterance(
        SoundDeviceMicrophone(settings.voice.input_device), SileroVAD(), _endpoint(settings)
    )
    if audio is None:
        print("✗ não ouvi nada; confira o microfone com 'shiro voice devices'")
        return 1
    await player.play(cues.done)
    transcript = await stt.transcribe(audio)
    took = _seconds(transcript.latency_ms / 1000)
    print(f"ouvi ({_seconds(audio.duration)}, transcrito em {took}):")
    print(f"  {transcript.text or '(nada reconhecível)'}")
    return 0


SAMPLES_DIR = "voice-samples"
_MANIFEST = "frases.json"


def record_phrases(settings: Settings) -> list[str]:
    """Comandos para gravar: os apps configurados primeiro, depois o resto do dia a dia."""
    apps = [entry.label for entry in settings.policy.allowed_apps.values()]
    phrases = [f"abra o {app}" for app in apps[:6]]
    if len(apps) > 1:
        phrases.append(f"feche o {apps[1]}")
    return [
        *phrases,
        "abaixa o volume pra vinte",
        "pausa a música",
        "que horas são",
        "o que eu tenho essa semana",
        "anota prova de cálculo sexta às dez",
        "me lembra de beber água daqui a vinte minutos",
        "quanto de memória ram eu tô usando",
    ]


async def _record(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.application.voice.listening import record_utterance
    from shiro.domain.voice.audio import Cues
    from shiro.infrastructure.voice.devices import SoundDeviceMicrophone, SoundDevicePlayer
    from shiro.infrastructure.voice.silero import SileroVAD

    phrases = record_phrases(settings)[: args.count or None]
    stamp = datetime.now(ZoneInfo(settings.general.timezone)).strftime("%Y%m%d-%H%M%S")
    folder = paths.data_dir() / SAMPLES_DIR / stamp
    folder.mkdir(parents=True)
    player = SoundDevicePlayer(settings.voice.output_device)
    cues = Cues.generate(settings.voice.cue_volume)
    print(f"Vou pedir {len(phrases)} frases. Fale do jeito normal, depois do bipe.")
    print(f"As gravações ficam só neste PC, em {folder}.\n")
    saved: list[dict[str, str]] = []
    for number, phrase in enumerate(phrases, start=1):
        print(f"[{number}/{len(phrases)}] diga: {phrase}")
        await player.play(cues.listening)
        audio = await record_utterance(
            SoundDeviceMicrophone(settings.voice.input_device), SileroVAD(), _endpoint(settings)
        )
        if audio is None:
            print("  não ouvi nada; pulando esta")
            continue
        await player.play(cues.done)
        name = f"{number:02d}.wav"
        (folder / name).write_bytes(audio.to_wav())
        saved.append({"file": name, "text": phrase})
        print(f"  ok ({_seconds(audio.duration)})")
    (folder / _MANIFEST).write_text(json.dumps(saved, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n{len(saved)} gravações salvas. Para medir: uv run shiro voice bench --samples")
    return 0 if saved else 1


def load_samples(spec: str) -> list[tuple[str, Any]]:
    """Gravações de ``shiro voice record``: ``"latest"`` ou o caminho de uma pasta."""
    from shiro.domain.voice.audio import Audio

    root = paths.data_dir() / SAMPLES_DIR
    if spec == "latest":
        folders = sorted(p for p in root.glob("*") if (p / _MANIFEST).is_file())
        if not folders:
            msg = "nenhuma gravação ainda: rode 'uv run shiro voice record' antes"
            raise FileNotFoundError(msg)
        folder = folders[-1]
    else:
        folder = Path(spec)
    items = json.loads((folder / _MANIFEST).read_text("utf-8"))
    return [(i["text"], Audio.from_wav((folder / i["file"]).read_bytes())) for i in items]


async def _setup(settings: Settings, args: argparse.Namespace) -> int:
    """Prepara tudo o que precisa de download: ouvido, voz e memória."""
    voice = await _setup_voice(settings)
    memory = await _setup_memory(settings)
    return voice or memory


async def _setup_voice(settings: Settings) -> int:
    import httpx

    from shiro.infrastructure.voice.models import DownloadError, ensure_kokoro, kokoro_installed
    from shiro.infrastructure.voice.silero import SileroVAD

    SileroVAD()
    print("✓ detector de fala (Silero VAD)")
    try:
        stt = await _ready_stt(settings)
    except (DownloadError, httpx.HTTPError) as exc:
        print(f"\n✗ {exc}")
        return 1
    started = time.perf_counter()
    await stt.load()
    print(f"✓ {stt.name} pronto (carregou em {_seconds(time.perf_counter() - started)})")
    tts_settings = settings.voice.tts
    if tts_settings.engine != "kokoro":
        print(f"✓ voz: {tts_settings.sapi_voice} do Windows (nada a baixar)")
        return 0
    if not kokoro_installed():
        print("✗ pacote kokoro-onnx ausente: rode 'uv sync' na pasta do projeto")
        return 1

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            files = await ensure_kokoro(
                client, paths.data_dir(), tts_settings.kokoro_model, _progress
            )
    except (DownloadError, httpx.HTTPError) as exc:
        print(f"\n✗ {exc}")
        return 1
    print(f"✓ Kokoro em {files.model.parent}")
    tts, status = _tts(settings, "kokoro")
    try:
        audio = await tts.synthesize("Sistema de voz pronto.")
    finally:
        await tts.aclose()
    print(f"✓ {status}: teste gerou {_seconds(audio.duration)} de fala")
    return 0


async def _setup_memory(settings: Settings) -> int:
    import httpx

    from shiro.infrastructure.embeddings.setup import build_embedder, ensure_embedding_model
    from shiro.infrastructure.system.downloads import DownloadError

    memory = settings.memory
    if not memory.enabled:
        return 0
    if "/" not in memory.embedding_model:
        print(
            f"! memória: '{memory.embedding_model}' não é um modelo do Hugging Face; uso a reserva"
        )
        return 0
    try:
        timeout = httpx.Timeout(30.0, read=60.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            await ensure_embedding_model(client, memory, paths.data_dir(), _progress)
    except (DownloadError, httpx.HTTPError) as exc:
        print(f"\n✗ memória: {exc} (continuo com a reserva por palavras)")
        return 1
    embedder = build_embedder(memory, paths.data_dir())
    started = time.perf_counter()
    vectors = await embedder.embed(["eu torço pro Coritiba", "qual é o meu time?"], query=False)
    score = float(vectors[0] @ vectors[1])
    took = _seconds(time.perf_counter() - started)
    print(f"✓ memória: {embedder.name} pronto ({took}; teste de semelhança {score:.2f})")
    return 0


# ---------------------------------------------------------------------- avaliação

BENCH_PHRASES = (
    "abaixa o volume pra vinte",
    "abre o spotify",
    "pula essa música",
    "como tá o tempo hoje",
    "o que eu tenho essa semana",
    "terminei o trabalho de cálculo",
    "tenho prova de física dia doze às sete da noite",
    "me lembra de tirar a roupa do varal às seis",
    "anota que eu preciso comprar café",
    "quanto de memória ram eu tô usando",
)


_DEADLINE_KEYS = ("due_text", "when_text")
_WER_OK = 0.25


def command_meaning(calls: Any, now: datetime) -> Any:
    """Chamadas do Tier 0 comparáveis: prazos viram data e hora, textos são normalizados.

    "às sete da noite" e "a 7 da noite" são o mesmo comando.
    """
    from shiro.domain.activities.dates import resolve
    from shiro.domain.text import normalize

    if not calls:
        return None
    meaning: list[tuple[str, dict[str, object]]] = []
    for call in calls:
        args: dict[str, object] = {}
        for key, value in call.arguments.items():
            if key in _DEADLINE_KEYS and isinstance(value, str):
                args[key] = resolve(value, now=now).when
            elif isinstance(value, str):
                args[key] = normalize(value).rstrip(".")
            else:
                args[key] = value
        meaning.append((call.name, args))
    return meaning


def word_error_rate(reference: str, hypothesis: str) -> float:
    from shiro.domain.text import normalize

    ref = normalize(reference).split()
    hyp = normalize(hypothesis).split()
    if not ref:
        return float(bool(hyp))
    row = list(range(len(hyp) + 1))
    for i, word in enumerate(ref, start=1):
        previous, row[0] = row[0], i
        for j, other in enumerate(hyp, start=1):
            current = min(row[j] + 1, row[j - 1] + 1, previous + (word != other))
            previous, row[j] = row[j], current
    return row[len(hyp)] / len(ref)


async def _bench(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.application.activities.rules import ActivityRules
    from shiro.application.agent.router import IntentRouter
    from shiro.bootstrap.tools import app_aliases
    from shiro.infrastructure.voice.models import kokoro_files, kokoro_installed
    from shiro.infrastructure.voice.tts import TTSError

    samples: str | None = getattr(args, "samples", None)
    engines: list[str] = args.engine or []
    if not engines and samples is None:
        if (
            kokoro_installed()
            and kokoro_files(paths.data_dir(), settings.voice.tts.kokoro_model).present
        ):
            engines.append("kokoro")
        if sys.platform == "win32":
            engines.append("sapi")
    models: list[str] = args.stt or [settings.voice.stt.model]
    devices: list[str] = getattr(args, "device", None) or [settings.voice.stt.device]
    hotword_modes = {"on": [True], "off": [False], "both": [True, False]}[
        getattr(args, "hotwords", "on") or "on"
    ]
    now = datetime.now(ZoneInfo(settings.general.timezone))
    router = IntentRouter(
        apps=app_aliases(settings),
        cloud_triggers=settings.router.cloud_triggers,
        rules=(ActivityRules(lambda: now),),
    )

    def intent(text: str) -> object:
        return command_meaning(router.match_tier0(text), now)

    report: dict[str, Any] = {"tts": {}, "stt": []}
    clips: dict[str, list[tuple[str, Any]]] = {}
    if samples is not None:
        try:
            clips["sua voz"] = load_samples(samples)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"✗ {exc}")
            return 1
        print(f"{len(clips['sua voz'])} gravações suas")
    for engine in engines:
        try:
            tts, status = _tts(settings, engine)
        except TTSError as exc:
            print(f"✗ {engine}: {exc}")
            continue
        times: list[float] = []
        clips[engine] = []
        try:
            for phrase in BENCH_PHRASES:
                started = time.perf_counter()
                audio = await tts.synthesize(phrase)
                times.append(time.perf_counter() - started)
                clips[engine].append((phrase, audio))
        finally:
            await tts.aclose()
        speech = sum(a.duration for _, a in clips[engine])
        rtf = sum(times) / speech if speech else 0.0
        median = _seconds(statistics.median(times))
        print(f"voz {status}: síntese mediana {median}, fator de tempo real {rtf:.2f}")
        report["tts"][engine] = {"median_s": statistics.median(times), "rtf": rtf}

    summary: list[str] = []
    for model in models:
        for device in devices:
            for hotwords in hotword_modes:
                label = f"{model} · {device} · {'com' if hotwords else 'sem'} hotwords"
                try:
                    stt = await _ready_stt(settings, model, hotwords=hotwords, device=device)
                    started = time.perf_counter()
                    await stt.load()
                except Exception as exc:
                    print(f"\n✗ {label}: {exc}")
                    continue
                print(f"\n{label} (carregado em {_seconds(time.perf_counter() - started)})")
                for engine, items in clips.items():
                    rows: list[dict[str, Any]] = []
                    for phrase, audio in items:
                        transcript = await stt.transcribe(audio)
                        expected, got = intent(phrase), intent(transcript.text)
                        wer = word_error_rate(phrase, transcript.text)
                        # Sem comando do Tier 0 (pergunta ao modelo), vale a fidelidade do texto.
                        ok = expected == got if expected is not None else wer <= _WER_OK
                        rows.append(
                            {
                                "phrase": phrase,
                                "heard": transcript.text,
                                "latency_s": transcript.latency_ms / 1000,
                                "wer": wer,
                                "intent_ok": ok,
                            }
                        )
                        mark = "✓" if ok else "✗"
                        took = transcript.latency_ms / 1000
                        print(f"  {mark} [{engine}] {took:4.2f} s  {transcript.text}")
                    if not rows:
                        continue
                    wer = statistics.mean(r["wer"] for r in rows)
                    latency = statistics.median(r["latency_s"] for r in rows)
                    intents = sum(r["intent_ok"] for r in rows)
                    line = (
                        f"{label} [{engine}]: comando certo {intents}/{len(rows)}"
                        f" · erro de palavras {100 * wer:.0f}% · mediana {_seconds(latency)}"
                    )
                    print(f"  → {line}")
                    summary.append(line)
                    report["stt"].append(
                        {
                            "model": model,
                            "device": device,
                            "hotwords": hotwords,
                            "engine": engine,
                            "rows": rows,
                        }
                    )
    if len(summary) > 1:
        print("\nResumo:")
        for line in summary:
            print(f"  {line}")
    if getattr(args, "wake", False) and engines:
        first = next(iter(e for e in clips if e in engines))
        report["wake"] = await _bench_wake(settings, first)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nrelatório salvo em {args.out}")
    return 0


class _HeardBy:
    """Guarda o que o Whisper rápido ouviu, para o relatório."""

    def __init__(self, stt: Any) -> None:
        self._stt = stt
        self.heard: list[str] = []

    async def load(self) -> None:
        await self._stt.load()

    async def transcribe(self, audio: Any) -> Any:
        transcript = await self._stt.transcribe(audio)
        self.heard.append(transcript.text)
        return transcript


class _CollectedWake:
    def __init__(self) -> None:
        self.got: list[str] = []

    def wake(self) -> None:
        self.got.append("wake")

    def command(self, text: str) -> None:
        self.got.append(f"command:{text}")


WAKE_PHRASES = (
    ("Ei, Shiro.", "wake"),
    ("Ei Shiro, abre o Spotify.", "command"),
    ("Oi Shiro, que horas são?", "command"),
    ("Eu falei com a Shiro ontem à noite.", None),
    ("Tenho prova de física amanhã cedo.", None),
    ("Ei, você viu meu fone?", None),
)


async def _bench_wake(settings: Settings, engine: str) -> list[dict[str, Any]]:
    """Palavra de ativação com o Whisper rápido, sobre frases sintetizadas (sem tocar nada)."""
    from shiro.infrastructure.voice.replay import ReplayMicrophone
    from shiro.infrastructure.voice.silero import SileroVAD
    from shiro.infrastructure.voice.wake import WakeListener

    word = settings.voice.wake_word
    tts, _ = _tts(settings, engine)
    check = await _ready_stt(settings, word.check_model)
    full = await _ready_stt(settings)
    await check.load()
    await full.load()
    print(f"\npalavra de ativação ({check.name} confere, {full.name} transcreve):")
    rows: list[dict[str, Any]] = []
    try:
        for phrase, expected in WAKE_PHRASES:
            audio = await tts.synthesize(phrase)
            events = _CollectedWake()
            got = events.got
            heard = _HeardBy(check)
            listener = WakeListener(
                microphone=ReplayMicrophone([audio]), events=events, is_idle=lambda: True
            )
            started = time.perf_counter()
            await listener.run_whisper(
                vad=SileroVAD(),
                check=heard,
                full=full,
                phrases=word.phrases,
                listen=_endpoint(settings),
                max_phrase_s=word.max_phrase_s,
            )
            kind = got[0].split(":", 1)[0] if got else None
            ok = kind == expected
            rows.append(
                {"phrase": phrase, "heard": heard.heard, "expected": expected, "got": got, "ok": ok}
            )
            mark = "✓" if ok else "✗"
            took = _seconds(time.perf_counter() - started)
            print(f"  {mark} {phrase:40} → {', '.join(got) or 'ignorada'} ({took})")
            print(f"      ouviu: {' | '.join(heard.heard) or '(nada)'}")
    finally:
        await tts.aclose()
    return rows
