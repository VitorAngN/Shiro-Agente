"""Identificadores ordenáveis por tempo (UUIDv7, RFC 9562)."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> str:
    """Gera um UUIDv7: 48 bits de timestamp em ms seguidos de bits aleatórios."""
    millis = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # versão 7
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variante RFC 9562
    value |= rand & ((1 << 62) - 1)  # rand_b (62 bits)
    return str(uuid.UUID(int=value))
