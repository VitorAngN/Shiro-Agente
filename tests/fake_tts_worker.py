"""Dublê do kokoro_worker para os testes: mesmo protocolo, áudio sintético.

python -m tests.fake_tts_worker [ok|broken|die]
"""

from __future__ import annotations

import json
import sys

import numpy as np


def main(mode: str) -> int:
    out = sys.stdout.buffer
    if mode == "broken":
        out.write(json.dumps({"error": "modelo corrompido"}).encode() + b"\n")
        out.flush()
        return 1
    out.write(json.dumps({"ready": True, "voices": ["pf_dora", "pm_alex"]}).encode() + b"\n")
    out.flush()
    for line in sys.stdin.buffer:
        request = json.loads(line)
        if mode == "die":
            return 3
        if request["text"] == "falhe":
            out.write(json.dumps({"error": "ValueError: texto ruim"}).encode() + b"\n")
            out.flush()
            continue
        count = 240 * len(request["text"])
        pcm = (np.sin(np.arange(count) / 10) * 8000).astype("<i2").tobytes()
        out.write(json.dumps({"rate": 24000, "bytes": len(pcm)}).encode() + b"\n")
        out.write(pcm)
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "ok"))
