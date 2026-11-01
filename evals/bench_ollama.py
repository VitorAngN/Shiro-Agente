"""Benchmark de modelo local no Ollama com o formato de pedido do SHIRO.

Roda os casos de ``evals/datasets/comandos_ptbr.jsonl`` contra um modelo do
Ollama usando uma persona e um conjunto de ferramentas parecidos com os do
SHIRO, e mede:

* velocidade de leitura do pedido completo (persona + ferramentas);
* velocidade de geração;
* latência por comando;
* acerto da ferramenta escolhida e dos argumentos (prévia da avaliação do marco 1a).

Só usa a biblioteca padrão, para rodar em qualquer Python 3.12+ sem instalar nada:

    python evals/bench_ollama.py --model qwen3:4b-instruct
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

NS = 1_000_000_000
APPS = ["spotify", "vscode", "chrome", "discord"]

SYSTEM_PROMPT = "\n".join(
    [
        "Você é o Shiro, assistente pessoal por voz que roda no PC Windows do usuário.",
        "Responda sempre em português do Brasil, em no máximo duas frases curtas,",
        "porque a resposta será falada.",
        "",
        "Regras:",
        "- Use uma ferramenta sempre que o pedido envolver uma ação no PC, lembretes",
        "  ou atividades.",
        "- Pedidos com várias ações: chame uma ferramenta para cada ação.",
        "- Nunca diga que fez algo sem ter chamado a ferramenta correspondente. Só a",
        "  ferramenta executa ações; sua resposta apenas confirma o que ela fez.",
        "- Nunca invente argumentos. Se faltar informação essencial (qual app, qual atividade,",
        "  qual prazo), pergunte antes de agir.",
        "- Prazos de atividades: copie a expressão de tempo exatamente como o usuário falou",
        "  em due_text; não converta para data.",
        "- Se o pedido for perigoso ou não existir ferramenta para ele (por exemplo, apagar",
        "  pastas do sistema), recuse em uma frase.",
        "- Perguntas gerais e contas: responda direto, sem ferramenta.",
    ]
)


def _tool(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    props = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": list(props)},
        },
    }


def _str(description: str, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        schema["enum"] = enum
    return schema


def _int(description: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "description": description, "minimum": minimum, "maximum": maximum}


TOOLS = [
    _tool(
        "set_volume", "Define o volume geral do PC.", {"level": _int("Volume de 0 a 100", 0, 100)}
    ),
    _tool(
        "change_volume",
        "Aumenta ou diminui o volume em relação ao atual. Use 10 ou -10 para 'um pouco'.",
        {"delta": _int("Variação de -100 a 100", -100, 100)},
    ),
    _tool("open_app", "Abre um aplicativo permitido.", {"app": _str("Aplicativo", APPS)}),
    _tool("close_app", "Fecha um aplicativo permitido.", {"app": _str("Aplicativo", APPS)}),
    _tool(
        "media_control",
        "Controla a mídia que está tocando.",
        {"action": _str("Ação", ["play", "pause", "next", "previous"])},
    ),
    _tool(
        "system_info",
        "Informa o uso de recursos do PC.",
        {"metric": _str("Recurso", ["cpu", "ram", "gpu", "disk", "battery"])},
    ),
    _tool("get_time", "Informa a data e a hora atuais."),
    _tool("get_weather", "Informa o clima atual.", {"city": _str("Cidade")}),
    _tool(
        "create_reminder",
        "Cria um lembrete para um horário.",
        {
            "text": _str("O que lembrar, sem o horário"),
            "when_text": _str("Quando, exatamente como o usuário falou ('às 20h')"),
        },
    ),
    _tool(
        "create_activity",
        "Registra uma atividade com prazo (trabalho, prova, entrega).",
        {
            "title": _str("Título curto da atividade"),
            "due_text": _str("Expressão de prazo exatamente como o usuário falou"),
        },
    ),
    _tool(
        "list_activities",
        "Lista as atividades de um período.",
        {"period": _str("Período", ["today", "tomorrow", "this_week", "next_week", "all"])},
    ),
    _tool(
        "complete_activity",
        "Marca uma atividade como concluída.",
        {"query": _str("Título ou parte do título da atividade")},
    ),
    _tool(
        "postpone_activity",
        "Muda o prazo de uma atividade.",
        {
            "query": _str("Título ou parte do título da atividade"),
            "due_text": _str("Novo prazo exatamente como o usuário falou"),
        },
    ),
]


def post(host: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not host.startswith(("http://127.0.0.1", "http://localhost")):
        msg = "o benchmark só conversa com um Ollama local"
        raise SystemExit(msg)
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - host validado acima
        host + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310
        return json.loads(response.read())


def chat(
    host: str, model: str, num_ctx: int, text: str, num_gpu: int | None = None
) -> dict[str, Any]:
    options: dict[str, Any] = {"num_ctx": num_ctx, "temperature": 0}
    if num_gpu is not None:
        options["num_gpu"] = num_gpu
    started = time.perf_counter()
    result = post(
        host,
        "/api/chat",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "tools": TOOLS,
            "stream": False,
            "keep_alive": "10m",
            "options": options,
        },
    )
    result["wall_s"] = time.perf_counter() - started
    return result


def rate(count: int, duration_ns: int) -> float:
    return count / (duration_ns / NS) if duration_ns else 0.0


def calls_of(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    calls = result.get("message", {}).get("tool_calls") or []
    return [(c["function"]["name"], c["function"].get("arguments") or {}) for c in calls]


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold().strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def args_match(expected: dict[str, Any], got: dict[str, Any]) -> bool:
    """Texto confere se um contém o outro, sem diferenciar maiúsculas nem acentos."""
    for key, want in expected.items():
        have = got.get(key)
        if isinstance(want, str):
            a, b = _plain(want), _plain(str(have or ""))
            if not a or not b or (a not in b and b not in a):
                return False
        elif have != want:
            return False
    return True


def score(case: dict[str, Any], result: dict[str, Any]) -> tuple[bool, bool]:
    """Devolve (ferramenta certa, argumentos certos)."""
    got = calls_of(result)
    expected = case["chamadas"]
    if not expected:
        ok = not got
        if ok and "resposta_contem" in case:
            ok = case["resposta_contem"] in result.get("message", {}).get("content", "")
        return ok, ok
    names_ok = Counter(n for n, _ in got) == Counter(c["tool"] for c in expected)
    if not names_ok:
        return False, False
    remaining = list(got)
    for call in expected:
        match = next(
            (g for g in remaining if g[0] == call["tool"] and args_match(call["args"], g[1])), None
        )
        if match is None:
            return True, False
        remaining.remove(match)
    return True, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark de modelo local no Ollama.")
    parser.add_argument("--model", default="qwen3:4b-instruct")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument(
        "--num-gpu",
        type=int,
        help="camadas na GPU (99 = todas); sem a opção, o Ollama decide",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "datasets" / "comandos_ptbr.jsonl",
    )
    parser.add_argument("--out", type=Path, help="salva o relatório em JSON")
    args = parser.parse_args()

    cases = [
        json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    gpu_note = "automático" if args.num_gpu is None else str(args.num_gpu)
    print(
        f"Modelo: {args.model} | contexto: {args.num_ctx} | num_gpu: {gpu_note}"
        f" | casos: {len(cases)}"
    )
    warm = chat(args.host, args.model, args.num_ctx, "oi", args.num_gpu)
    full_prompt = warm.get("prompt_eval_count", 0)
    full_rate = rate(full_prompt, warm.get("prompt_eval_duration", 0))
    print(f"Carga do modelo: {warm.get('load_duration', 0) / NS:.2f} s")
    print(f"Pedido completo (persona + {len(TOOLS)} ferramentas): {full_prompt} tokens")
    print(f"Leitura do pedido completo: {full_rate:.0f} tokens/s")

    for loaded in post(args.host, "/api/ps").get("models", []):
        if loaded.get("name") == args.model or loaded.get("model") == args.model:
            size, vram = loaded.get("size", 0), loaded.get("size_vram", 0)
            gpu = 100 * vram / size if size else 0
            print(f"Memória: {size / 2**30:.2f} GB, {gpu:.0f}% na GPU")

    print()
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = chat(args.host, args.model, args.num_ctx, case["fala"], args.num_gpu)
        tool_ok, args_ok = score(case, result)
        got = calls_of(result)
        rows.append(
            {
                "id": case["id"],
                "fala": case["fala"],
                "tool_ok": tool_ok,
                "args_ok": args_ok,
                "chamadas": [{"tool": n, "args": a} for n, a in got],
                "resposta": result.get("message", {}).get("content", ""),
                "latencia_s": result["wall_s"],
                "geracao_tps": rate(result.get("eval_count", 0), result.get("eval_duration", 0)),
                "tokens_gerados": result.get("eval_count", 0),
            }
        )
        mark = "✓" if args_ok else ("~" if tool_ok else "✗")
        shown = ", ".join(f"{n}({json.dumps(a, ensure_ascii=False)})" for n, a in got)
        shown = shown or "sem ferramenta: " + rows[-1]["resposta"][:70].replace("\n", " ")
        print(f"{mark} {case['id']:<8} {result['wall_s']:5.2f} s  {shown}")

    latencies = [r["latencia_s"] for r in rows]
    speeds = [r["geracao_tps"] for r in rows if r["tokens_gerados"] >= 5]
    tools_hit = sum(r["tool_ok"] for r in rows)
    args_hit = sum(r["args_ok"] for r in rows)
    total = len(rows)
    p50, worst = statistics.median(latencies), max(latencies)
    print()
    print(f"Ferramenta certa: {tools_hit}/{total} ({100 * tools_hit / total:.0f}%)")
    print(f"Ferramenta e argumentos certos: {args_hit}/{total} ({100 * args_hit / total:.0f}%)")
    print(f"Latência por comando: p50 {p50:.2f} s | máx {worst:.2f} s")
    if speeds:
        print(f"Geração: {statistics.median(speeds):.1f} tokens/s (mediana)")

    if args.out:
        report = {
            "model": args.model,
            "num_ctx": args.num_ctx,
            "num_gpu": args.num_gpu,
            "full_prompt_tokens": full_prompt,
            "full_prompt_tps": full_rate,
            "cases": rows,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Relatório salvo em {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
