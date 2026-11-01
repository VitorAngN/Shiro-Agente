"""Processo separado que sintetiza a voz com Kokoro (ADR-0015).

O Kokoro em ONNX é MIT, mas a fonetização usa espeak-ng e phonemizer (GPL-3).
Para manter a fronteira de licença do SHIRO (MIT) clara, eles só são
importados aqui, num processo à parte, que conversa por stdin e stdout:

* pedido: uma linha JSON ``{"text": ..., "voice": ..., "speed": ..., "lang": ...}``;
* resposta: uma linha JSON ``{"rate": 24000, "bytes": N}`` seguida de N bytes de
  PCM 16 bits mono, ou ``{"error": "..."}`` sem bytes.

Na partida o processo escreve ``{"ready": true, "voices": [...]}``.

    python -m shiro.voice.kokoro_worker <modelo.onnx> <voices.bin>
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO


def _send(out: BinaryIO, header: dict[str, Any], payload: bytes = b"") -> None:
    out.write(json.dumps(header).encode() + b"\n")
    out.write(payload)
    out.flush()


def main(argv: list[str]) -> int:
    out = sys.stdout.buffer
    # Qualquer print de biblioteca vai para o stderr, nunca para o protocolo.
    sys.stdout = sys.stderr
    if len(argv) != 3:
        _send(out, {"error": "uso: kokoro_worker <modelo.onnx> <voices.bin>"})
        return 2
    try:
        import numpy as np
        from kokoro_onnx import Kokoro  # pyright: ignore[reportMissingImports]

        engine = Kokoro(argv[1], argv[2])
        voices = list(engine.get_voices())  # pyright: ignore[reportUnknownArgumentType]
    except Exception as exc:
        _send(out, {"error": f"{type(exc).__name__}: {exc}"})
        return 1
    _send(out, {"ready": True, "voices": voices})
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            samples, rate = engine.create(  # pyright: ignore[reportUnknownVariableType]
                request["text"],
                voice=request["voice"],
                speed=float(request.get("speed", 1.0)),
                lang=request.get("lang", "pt-br"),
            )
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()  # pyright: ignore[reportUnknownArgumentType]
            _send(out, {"rate": int(rate), "bytes": len(pcm)}, pcm)  # pyright: ignore[reportUnknownArgumentType]
        except Exception as exc:
            _send(out, {"error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
