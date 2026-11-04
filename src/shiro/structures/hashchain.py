"""Cadeia de hashes: lista encadeada em que cada elo aponta para o anterior pelo hash.

Cada registro guarda ``prev_hash`` (o hash do anterior) e ``hash`` =
SHA-256(prev_hash + campos). Alterar ou apagar um registro do meio muda o hash
dele, e o ``prev_hash`` do seguinte deixa de bater: a adulteração aparece na
verificação. É a mesma ideia dos commits do git.

Uso: o log de auditoria (``infrastructure.persistence.audit``), que guarda a
cadeia no SQLite. A retenção pode apagar o começo; por isso o primeiro registro
que sobrou vale como âncora, e a verificação confere daí em diante.

==============  ======
Operação        Custo
==============  ======
``link``        O(tamanho dos campos)
``verify``      O(n), num passo só, sem carregar tudo na memória
==============  ======
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

GENESIS = "0" * 64
_SEPARATOR = "\x1f"  # "unit separator": não aparece em texto comum


def link(prev_hash: str, fields: Sequence[str]) -> str:
    """O hash de um elo novo depois de ``prev_hash``."""
    material = _SEPARATOR.join((prev_hash, *fields))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainRecord:
    seq: int
    fields: tuple[str, ...]
    prev_hash: str
    hash: str


class ChainVerifier:
    """Confere a cadeia um registro por vez (dá para ler de um cursor, sem lista na memória)."""

    def __init__(self) -> None:
        self._expected_prev: str | None = None
        self.broken_at: int | None = None

    def feed(self, record: ChainRecord) -> bool:
        """``False`` no primeiro registro inválido (anotado em ``broken_at``) e daí em diante."""
        if self.broken_at is not None:
            return False
        linked = self._expected_prev is None or record.prev_hash == self._expected_prev
        if not linked or link(record.prev_hash, record.fields) != record.hash:
            self.broken_at = record.seq
            return False
        self._expected_prev = record.hash
        return True


def verify(records: Iterable[ChainRecord]) -> int | None:
    """``None`` se a cadeia está íntegra; senão, o ``seq`` do primeiro registro inválido."""
    verifier = ChainVerifier()
    for record in records:
        if not verifier.feed(record):
            break
    return verifier.broken_at
