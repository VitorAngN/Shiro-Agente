"""Avaliação do agente completo: Tier 0, modelo, política e ferramentas.

Diferente de ``bench_ollama.py``, que testa só o modelo, aqui cada caso passa
pelo ``AgentLoop`` real montado por ``build_app``. A área de trabalho é
simulada (nada muda no PC), o clima usa dados fixos e as confirmações são
aprovadas automaticamente. O banco fica numa pasta temporária.

    uv run python -m evals.run_agent              # modelo local
    uv run python -m evals.run_agent --cloud      # libera o Tier 2, se houver chave

O relógio é fixo (quarta-feira, 10h) para os prazos darem sempre o mesmo
resultado. Prazos são comparados pela data e hora que produzem depois de
ancorados na fala (ADR-0014): "às 20h" e "às oito da noite" valem o mesmo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from evals.bench_ollama import args_match
from shiro.activities import dates
from shiro.app import App, Desktop, build_app
from shiro.core.models import AgentResult, DecisionKind
from shiro.settings import AppEntry, Settings, load_settings
from shiro.tools.builtin.media import MediaAction
from shiro.tools.builtin.system import GB, Battery, GpuUsage, Usage

DATASET = Path(__file__).parent / "datasets" / "comandos_ptbr.jsonl"
# Quarta-feira, 4 de novembro de 2026, 10h, no fuso do shiro.toml.
EVAL_NOW = (2026, 11, 4, 10, 0)
DEADLINE_KEYS = {"due_text": "title", "when_text": "text"}

EVAL_APPS = {
    "spotify": AppEntry(launch="spotify:", process="Spotify.exe", name="Spotify"),
    "vscode": AppEntry(
        launch="code", process="Code.exe", name="VS Code", aliases=("vs code", "code")
    ),
    "discord": AppEntry(launch="discord:", process="Discord.exe", name="Discord"),
}


class SimVolume:
    def __init__(self) -> None:
        self.level = 50

    async def get_level(self) -> int:
        return self.level

    async def set_level(self, level: int) -> None:
        self.level = level


class SimMedia:
    async def press(self, action: MediaAction) -> None:
        return None


class SimLauncher:
    async def launch(self, target: str) -> None:
        return None

    async def close(self, process: str) -> int:
        return 1


class SimProbe:
    async def cpu_percent(self) -> float:
        return 12.0

    async def memory(self) -> Usage:
        return Usage(9.2 * GB, 23.8 * GB)

    async def disk(self) -> Usage:
        return Usage(300 * GB, 476 * GB)

    async def battery(self) -> Battery | None:
        return Battery(81, True)

    async def gpu(self) -> GpuUsage | None:
        return GpuUsage(3100, 4096, 35)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def eval_now(settings: Settings) -> datetime:
    return datetime(*EVAL_NOW, tzinfo=ZoneInfo(settings.general.timezone))


class AutoConfirm:
    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        return True


def fixed_weather() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding" in request.url.host:
            place = {"name": "Curitiba", "latitude": -25.43, "longitude": -49.27}
            return httpx.Response(200, json={"results": [place]})
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 20,
                    "apparent_temperature": 19,
                    "relative_humidity_2m": 80,
                    "weather_code": 3,
                },
                "daily": {
                    "temperature_2m_max": [24],
                    "temperature_2m_min": [15],
                    "precipitation_probability_max": [40],
                },
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def eval_settings(base: Settings, *, cloud: bool) -> Settings:
    return base.model_copy(
        update={
            "general": base.general.model_copy(update={"city": "Curitiba"}),
            "policy": base.policy.model_copy(
                update={"read_only_mode": False, "allowed_apps": EVAL_APPS}
            ),
            "llm": base.llm.model_copy(
                update={"cloud": base.llm.cloud.model_copy(update={"enabled": cloud})}
            ),
        }
    )


async def build_eval_app(settings: Settings, workdir: Path, **overrides: Any) -> App:
    overrides.setdefault("clock", FixedClock(eval_now(settings)))
    return await build_app(
        settings,
        confirmation=AutoConfirm(),
        database_path=workdir / "eval.db",
        data_dir=workdir,
        desktop=Desktop(volume=SimVolume(), media=SimMedia(), launcher=SimLauncher()),
        http=fixed_weather(),
        probe=SimProbe(),
        **overrides,
    )


def same_deadline(
    expected: str, got: object, args: Mapping[str, Any], key: str, utterance: str, now: datetime
) -> bool:
    """Mesmo prazo efetivo: o que a ferramenta resolveria depois de ancorar na fala."""
    title = str(args.get(DEADLINE_KEYS[key]) or "")
    spoken = dates.ground(str(got) if got else None, utterance, now=now, exclude=title)
    if dates.resolve(spoken, now=now).when is None:
        return dates.resolve(expected, now=now).when is None and args_match(
            {key: expected}, {key: spoken}
        )
    return dates.resolve(spoken, now=now).when == dates.resolve(expected, now=now).when


def call_matches(
    expected: Mapping[str, Any], got: Mapping[str, Any], utterance: str, now: datetime
) -> bool:
    plain = {k: v for k, v in expected.items() if k not in DEADLINE_KEYS}
    if not args_match(plain, dict(got)):
        return False
    return all(
        same_deadline(expected[key], got.get(key), got, key, utterance, now)
        for key in DEADLINE_KEYS
        if key in expected
    )


def score(
    case: dict[str, Any], result: AgentResult, now: datetime | None = None
) -> tuple[bool, bool]:
    """(ferramentas certas, ferramentas e argumentos certos)."""
    now = now or datetime(*EVAL_NOW, tzinfo=ZoneInfo("America/Sao_Paulo"))
    got = [(c.call.name, c.call.arguments) for c in result.calls]
    expected: list[dict[str, Any]] = case["chamadas"]
    if not expected:
        ok = not got and not result.claim_blocked
        if "resposta_contem" in case:
            ok = ok and case["resposta_contem"] in result.text
        return ok, ok
    if Counter(name for name, _ in got) != Counter(call["tool"] for call in expected):
        return False, False
    remaining = list(got)
    for call in expected:
        match = next(
            (
                g
                for g in remaining
                if g[0] == call["tool"]
                and call_matches(call["args"], g[1], case.get("fala", ""), now)
            ),
            None,
        )
        if match is None:
            return True, False
        remaining.remove(match)
    return True, True


async def evaluate(app: App, cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = eval_now(app.settings)
    for case in cases:
        app.agent.reset()
        result = await app.agent.run_turn(case["fala"])
        tools_ok, args_ok = score(case, result, now)
        rows.append(
            {
                "id": case["id"],
                "fala": case["fala"],
                "tier": result.tier.value,
                "tier_esperado": case.get("tier_esperado"),
                "tools_ok": tools_ok,
                "args_ok": args_ok,
                "claim_blocked": result.claim_blocked,
                "latency_ms": result.latency_ms,
                # Tokens lidos do pedido: baixo quando o prefixo veio do cache (ADR-0011).
                "prompt_tokens": result.usage.prompt_tokens,
                "calls": [{"tool": c.call.name, "args": c.call.arguments} for c in result.calls],
                "resposta": result.text,
            }
        )
    return rows


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    latencies = sorted(r["latency_ms"] for r in rows)
    p95_index = max(0, round(0.95 * (total - 1)))
    return {
        "casos": total,
        "ferramenta_certa": sum(r["tools_ok"] for r in rows) / total,
        "argumentos_certos": sum(r["args_ok"] for r in rows) / total,
        "por_camada": dict(Counter(r["tier"] for r in rows)),
        "acoes_alegadas_bloqueadas": sum(r["claim_blocked"] for r in rows),
        "latencia_p50_ms": statistics.median(latencies),
        "latencia_p95_ms": latencies[p95_index],
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases(args.dataset)
    if args.only:
        cases = [c for c in cases if c["id"].startswith(tuple(args.only))]
    settings = eval_settings(load_settings(), cloud=args.cloud)
    with tempfile.TemporaryDirectory(prefix="shiro-eval-") as tmp:
        app = await build_eval_app(settings, Path(tmp))
        try:
            await app.agent.warm_up()
            print(f"Modelo local: {settings.llm.local.model} | {app.cloud_status}")
            rows = await evaluate(app, cases)
        finally:
            await app.aclose()
    for row in rows:
        mark = "✓" if row["args_ok"] else ("~" if row["tools_ok"] else "✗")
        calls = ", ".join(
            f"{c['tool']}({json.dumps(c['args'], ensure_ascii=False)})" for c in row["calls"]
        )
        shown = calls or "sem ferramenta: " + row["resposta"][:60].replace("\n", " ")
        tokens = f"{row['prompt_tokens']:>5}t" if row["prompt_tokens"] else "      "
        print(
            f"{mark} {row['id']:<8} {row['tier']} {row['latency_ms'] / 1000:5.2f} s"
            f" {tokens}  {shown}"
        )
    summary = summarize(rows)
    print()
    print(f"Ferramenta certa: {summary['ferramenta_certa']:.0%}")
    print(f"Ferramenta e argumentos certos: {summary['argumentos_certos']:.0%}")
    print(f"Por camada: {summary['por_camada']}")
    print(f"Ações alegadas bloqueadas: {summary['acoes_alegadas_bloqueadas']}")
    print(
        f"Latência p50 {summary['latencia_p50_ms'] / 1000:.2f} s"
        f" | p95 {summary['latencia_p95_ms'] / 1000:.2f} s"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        report = {"resumo": summary, "casos": rows}
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Relatório salvo em {args.out}")
    return 0


def main() -> int:
    # No Windows, saída redirecionada usa cp1252 e quebra com "✓".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # pyright: ignore[reportAttributeAccessIssue]
    parser = argparse.ArgumentParser(description="Avaliação do agente completo da SHIRO.")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--cloud", action="store_true", help="libera o Tier 2 (nuvem)")
    parser.add_argument("--only", nargs="*", help="só os casos com esses prefixos de id")
    parser.add_argument("--out", type=Path, help="salva o relatório em JSON")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
