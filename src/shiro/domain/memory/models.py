"""Fatos guardados e a porta de persistência da memória."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from shiro.domain.memory.embedding import Vectors

Category = Literal["preferencia", "pessoa", "projeto", "outro"]


class MemoryFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    category: Category = "outro"
    created_at: datetime
    last_used_at: datetime | None = None


class MemoryStore(Protocol):
    async def add(self, fact: MemoryFact, vector: Vectors, model: str) -> None: ...

    async def all(self) -> list[MemoryFact]: ...

    async def vectors(self, model: str) -> dict[str, Vectors]:
        """Vetores do modelo dado, por id do fato (fatos sem vetor desse modelo ficam fora)."""
        ...

    async def set_vectors(self, items: Sequence[tuple[str, Vectors]], model: str) -> None: ...

    async def delete(self, fact_ids: Sequence[str]) -> int: ...

    async def touch(self, fact_ids: Sequence[str], when: datetime) -> None: ...

    async def revision(self) -> int:
        """Muda quando outro processo altera o banco (o painel, outra janela do ``shiro``).

        Quem guarda os fatos em memória relê tudo quando a revisão muda.
        """
        ...
