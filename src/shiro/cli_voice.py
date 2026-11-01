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

from shiro import __version__, paths
from shiro.settings import Settings


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
    actions.add_parser("setup", help="baixa e prepara os modelos de voz")
    bench = actions.add_parser("bench", help="mede fala e transcrição sem tocar áudio")
    bench.add_argument("--engine", nargs="*", choices=("kokoro", "sapi"), help="motores de voz")
    bench.add_argument("--stt", nargs="*", help="modelos do Whisper (ex.: base small)")
    bench.add_argument("--out", type=Path, help="salva o relatório em JSON")


def run_voice(settings: Settings, args: argparse.Namespace) -> int:
    command = args.voice_command
    if command == "devices":
        return _devices()
    handlers = {
        None: _session,
        "say": _say,
        "listen": _listen,
        "setup": _setup,
        "bench": _bench,
    }
    try:
        return asyncio.run(handlers[command](settings, args))
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------- utilidades


def _tts(settings: Settings, engine: str | None = None) -> Any:
    from shiro.voice.tts import build_tts

    tts_settings = settings.voice.tts
    if engine is not None:
        tts_settings = tts_settings.model_copy(update={"engine": engine})
    return build_tts(tts_settings, paths.data_dir())


def _app_labels(settings: Settings) -> list[str]:
    return [entry.label for entry in settings.policy.allowed_apps.values()]


def _stt(settings: Settings, model: str | None = None) -> Any:
    from shiro.voice.stt import FasterWhisperSTT, vocabulary_prompt

    stt_settings = settings.voice.stt
    if model is not None:
        stt_settings = stt_settings.model_copy(update={"model": model})
    prompt = vocabulary_prompt(settings.general.assistant_name, _app_labels(settings))
    return FasterWhisperSTT(stt_settings, prompt=prompt)


def _endpoint(settings: Settings) -> Any:
    from shiro.voice.vad import EndpointConfig

    listen = settings.voice.listen
    return EndpointConfig(
        threshold=listen.threshold,
        start_timeout_s=listen.start_timeout_s,
        end_silence_ms=listen.end_silence_ms,
        max_utterance_s=listen.max_utterance_s,
        pre_roll_ms=listen.pre_roll_ms,
    )


def _seconds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " s"


# ---------------------------------------------------------------------- sessão


async def _session(settings: Settings, args: argparse.Namespace) -> int:
    from shiro.app import build_app
    from shiro.core.ports import LLMError
    from shiro.interfaces.text import CliConfirmation, llm_down_message, use_safe_output
    from shiro.interfaces.theme import Theme
    from shiro.interfaces.voice import (
        TriggerSource,
        VoiceConfirmation,
        VoiceNotifier,
        VoiceSession,
    )
    from shiro.observability.logging import configure_logging
    from shiro.voice.audio import Cues
    from shiro.voice.devices import AudioDeviceError, SoundDeviceMicrophone, SoundDevicePlayer
    from shiro.voice.tts import TTSError
    from shiro.voice.vad import SileroVAD

    use_safe_output()
    configure_logging(settings.logging, paths.log_dir(), console=False)
    theme = Theme.for_stream(sys.stdout)
    voice = settings.voice
    try:
        tts, tts_status = _tts(settings)
    except TTSError as exc:
        print(theme.status(False, str(exc)))
        return 1
    stt = _stt(settings)
    confirmation = VoiceConfirmation(keyboard=CliConfirmation(theme=theme))
    notifier = VoiceNotifier()
    app = await build_app(settings, confirmation=confirmation, notifier=notifier, channel="voice")
    session = VoiceSession(
        run_turn=app.agent.run_turn,
        stt=stt,
        tts=tts,
        player=SoundDevicePlayer(voice.output_device),
        microphone=SoundDeviceMicrophone(voice.input_device),
        detector=SileroVAD(),
        listen=_endpoint(settings),
        cues=Cues.generate(voice.cue_volume),
        name=settings.general.assistant_name,
        volume=voice.tts.volume,
        verbose=args.verbose,
        theme=theme,
    )
    confirmation.attach(session)
    notifier.attach(session)
    triggers = TriggerSource()
    hotkeys: Any = None
    try:
        session.print(theme.banner(__version__))
        if not args.no_warmup:
            try:
                await app.agent.warm_up()
                session.print(theme.status(True, f"{settings.llm.local.model} carregado"))
            except LLMError as exc:
                session.print(
                    theme.status(False, llm_down_message(settings.llm.local.base_url, exc))
                )
        session.print(theme.meta(f"carregando {stt.name} (na primeira vez, baixa o modelo)…"))
        await stt.load()
        session.print(theme.status(True, f"ouvido: {stt.name}"))
        start = getattr(tts, "start", None)
        if start is not None:
            await start()
        session.print(theme.status(True, tts_status))
        talk_hint = "Enter"
        if sys.platform == "win32":
            from shiro.voice.hotkeys import HotkeyError
            from shiro.voice.windows.hotkeys import WindowsHotkeys

            try:
                hotkeys = WindowsHotkeys(
                    {"talk": voice.push_to_talk_hotkey, "stop": voice.stop_hotkey}
                )
                hotkeys.start()
                triggers.add(hotkeys.next)
                talk_hint = f"{voice.push_to_talk_hotkey} (ou Enter)"
                session.print(
                    theme.status(
                        True,
                        f"atalhos: falar {voice.push_to_talk_hotkey}, parar {voice.stop_hotkey}",
                    )
                )
            except HotkeyError as exc:
                session.print(theme.status(False, f"{exc}; use Enter para falar"))
        app.start_background()
        session.print("")
        session.print(
            theme.meta(f"{talk_hint}: falar · digitar: mandar texto · p: parar · sair: encerrar")
        )
        triggers.add_terminal(input)
        await session.run(triggers)
    except (AudioDeviceError, TTSError) as exc:
        session.print(theme.status(False, str(exc)))
        return 1
    finally:
        if hotkeys is not None:
            hotkeys.stop()
        await triggers.aclose()
        await tts.aclose()
        await app.aclose()
    return 0


# ---------------------------------------------------------------------- utilitários


def _devices() -> int:
    from shiro.voice.devices import AudioDeviceError, list_devices

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
    from shiro.voice.devices import SoundDevicePlayer
    from shiro.voice.speech import for_speech
    from shiro.voice.tts import TTSError

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
    from shiro.voice.audio import Cues
    from shiro.voice.devices import SoundDeviceMicrophone, SoundDevicePlayer
    from shiro.voice.vad import SileroVAD, record_utterance

    stt = _stt(settings)
    print(f"carregando {stt.name}…")
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


async def _setup(settings: Settings, args: argparse.Namespace) -> int:
    import httpx

    from shiro.voice.models import DownloadError, ensure_kokoro, kokoro_installed
    from shiro.voice.vad import SileroVAD

    SileroVAD()
    print("✓ detector de fala (Silero VAD)")
    stt = _stt(settings)
    print(f"… {stt.name}: baixando e carregando (só demora na primeira vez)")
    started = time.perf_counter()
    await stt.load()
    print(f"✓ {stt.name} pronto em {_seconds(time.perf_counter() - started)}")
    tts_settings = settings.voice.tts
    if tts_settings.engine != "kokoro":
        print(f"✓ voz: {tts_settings.sapi_voice} do Windows (nada a baixar)")
        return 0
    if not kokoro_installed():
        print("✗ pacote kokoro-onnx ausente: rode 'uv sync' na pasta do projeto")
        return 1

    def progress(name: str, done: int, total: int | None) -> None:
        share = f"{100 * done / total:5.1f}%" if total else f"{done / 2**20:.0f} MB"
        print(f"\r  {name}: {share}", end="", flush=True)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            files = await ensure_kokoro(
                client, paths.data_dir(), tts_settings.kokoro_model, progress
            )
    except (DownloadError, httpx.HTTPError) as exc:
        print(f"\n✗ {exc}")
        return 1
    print(f"\n✓ Kokoro em {files.model.parent}")
    tts, status = _tts(settings, "kokoro")
    try:
        audio = await tts.synthesize("Sistema de voz pronto.")
    finally:
        await tts.aclose()
    print(f"✓ {status}: teste gerou {_seconds(audio.duration)} de fala")
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


def word_error_rate(reference: str, hypothesis: str) -> float:
    from shiro.core.text import normalize

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
    from shiro.activities.rules import ActivityRules
    from shiro.app import app_aliases
    from shiro.core.router import IntentRouter
    from shiro.voice.models import kokoro_files, kokoro_installed
    from shiro.voice.tts import TTSError

    engines: list[str] = args.engine or []
    if not engines:
        if (
            kokoro_installed()
            and kokoro_files(paths.data_dir(), settings.voice.tts.kokoro_model).present
        ):
            engines.append("kokoro")
        if sys.platform == "win32":
            engines.append("sapi")
    models: list[str] = args.stt or [settings.voice.stt.model]
    now = datetime.now(ZoneInfo(settings.general.timezone))
    router = IntentRouter(
        apps=app_aliases(settings),
        cloud_triggers=settings.router.cloud_triggers,
        rules=(ActivityRules(lambda: now),),
    )

    def intent(text: str) -> object:
        calls = router.match_tier0(text)
        return [(c.name, c.arguments) for c in calls] if calls else None

    report: dict[str, Any] = {"phrases": list(BENCH_PHRASES), "tts": {}, "stt": []}
    clips: dict[str, list[Any]] = {}
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
                clips[engine].append(audio)
        finally:
            await tts.aclose()
        speech = sum(a.duration for a in clips[engine])
        rtf = sum(times) / speech if speech else 0.0
        median = _seconds(statistics.median(times))
        print(f"voz {status}: síntese mediana {median}, fator de tempo real {rtf:.2f}")
        report["tts"][engine] = {"median_s": statistics.median(times), "rtf": rtf}

    for model in models:
        stt = _stt(settings, model)
        started = time.perf_counter()
        await stt.load()
        print(f"\n{stt.name} carregado em {_seconds(time.perf_counter() - started)}")
        for engine, audios in clips.items():
            rows: list[dict[str, Any]] = []
            for phrase, audio in zip(BENCH_PHRASES, audios, strict=True):
                transcript = await stt.transcribe(audio)
                expected, got = intent(phrase), intent(transcript.text)
                rows.append(
                    {
                        "phrase": phrase,
                        "heard": transcript.text,
                        "latency_s": transcript.latency_ms / 1000,
                        "wer": word_error_rate(phrase, transcript.text),
                        "intent_ok": expected is None or expected == got,
                    }
                )
                mark = "✓" if rows[-1]["intent_ok"] else "✗"
                print(
                    f"  {mark} [{engine}] {transcript.latency_ms / 1000:4.2f} s  {transcript.text}"
                )
            wer = statistics.mean(r["wer"] for r in rows)
            latency = statistics.median(r["latency_s"] for r in rows)
            intents = sum(r["intent_ok"] for r in rows)
            print(
                f"  → {engine}: comando certo {intents}/{len(rows)}"
                f" · erro de palavras {100 * wer:.0f}% · transcrição mediana {_seconds(latency)}"
            )
            report["stt"].append({"model": model, "engine": engine, "rows": rows})
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nrelatório salvo em {args.out}")
    return 0
