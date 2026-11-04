"""Memória de longo prazo: só o que o usuário pede para lembrar (RF-41 a RF-44).

Regras (docs/04-modelo-de-dados.md, seção 3):

* entra só o que foi pedido explicitamente ("lembra que…"), nunca inferências;
* senhas, tokens, documentos e dados bancários são recusados;
* tudo é ``local_only``: memória nunca vai para a nuvem. Um turno que usa
  memórias no contexto não sobe para o Tier 2.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from shiro.domain.ids import uuid7
from shiro.domain.memory.embedding import Embedder, shares_stem
from shiro.domain.memory.models import Category, MemoryFact, MemoryStore
from shiro.domain.models import ToolResult
from shiro.domain.ports import Clock
from shiro.domain.text import normalize
from shiro.structures.vector_index import VectorIndex

_SENSITIVE = re.compile(
    r"\b(?:senha|password|pin|token|chave (?:de )?api|api key|cpf|rg|cnh|passaporte"
    r"|cartao|cvv|conta bancaria|agencia|pix|codigo de seguranca)\b"
)
_LONG_NUMBER = re.compile(r"\d[\d .\-/]{7,}\d")
_SECRET_LIKE = re.compile(r"[A-Za-z0-9_\-]{24,}")
_CATEGORIES: tuple[tuple[Category, re.Pattern[str]], ...] = (
    ("preferencia", re.compile(r"\b(?:gosto|prefiro|favorit|odeio|detesto|curto|amo)\w*")),
    (
        "pessoa",
        re.compile(
            r"\b(?:mae|pai|irma|irmao|namorad|espos|amig|chefe|professor|primo|prima|filh|avo)\w*"
        ),
    ),
    ("projeto", re.compile(r"\b(?:projeto|materia|disciplina|curso|faculdade|estagio|tcc)\w*")),
)
_MAX_CHARS = 300


def is_sensitive(text: str) -> bool:
    plain = normalize(text)
    return bool(_SENSITIVE.search(plain) or _LONG_NUMBER.search(text) or _SECRET_LIKE.search(text))


def categorize(text: str) -> Category:
    plain = normalize(text)
    for category, pattern in _CATEGORIES:
        if pattern.search(plain):
            return category
    return "outro"


class MemoryService:
    def __init__(
        self,
        *,
        store: MemoryStore,
        embedder: Embedder,
        clock: Clock,
        max_in_context: int = 3,
        min_score: float | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._clock = clock
        self._max = max_in_context
        self._min_score = min_score if min_score is not None else embedder.relevant_score
        # Fatos e vetores em memória: cada turno busca no índice, não no SQLite.
        self._facts: dict[str, MemoryFact] = {}
        self._index: VectorIndex[str] = VectorIndex()
        self._revision: int | None = None

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    # ------------------------------------------------------------------ ações

    async def remember(self, text: str) -> ToolResult:
        content = text.strip().rstrip(".").strip()
        if not content:
            return ToolResult.failure("O que eu devo lembrar?")
        if len(content) > _MAX_CHARS:
            return ToolResult.failure("É muita coisa para uma memória. Pode resumir numa frase?")
        if is_sensitive(content):
            return ToolResult.failure(
                "Por segurança, não guardo senhas, documentos, números de conta nem códigos."
            )
        vector = (await self._embedder.embed([content], query=False))[0]
        await self._refresh()
        same = next(
            (f for f in self._facts.values() if normalize(f.content) == normalize(content)), None
        )
        if same is None:
            nearest = self._index.search(vector, 1)
            if nearest and nearest[0][1] >= 0.97:
                same = self._facts[nearest[0][0]]
        if same is not None:
            return ToolResult.success(f"Já sei disso: {same.content}.", say="Já sei disso.")
        fact = MemoryFact(
            id=uuid7(), content=content, category=categorize(content), created_at=self._clock.now()
        )
        await self._store.add(fact, vector, self._embedder.name)
        self._facts[fact.id] = fact
        self._index.add(fact.id, vector)
        return ToolResult.success(f"Guardado: {content}.", say="Guardado.")

    async def forget(self, query: str) -> ToolResult:
        found = await self.search(query, limit=3, min_score=self._embedder.match_score)
        # Apagar é definitivo: além da semelhança, exige uma palavra em comum.
        found = [(f, s) for f, s in found if shares_stem(query, f.content)]
        if not found:
            return ToolResult.failure(f'Não achei nenhuma memória sobre "{query.strip()}".')
        best, score = found[0]
        close = [f for f, s in found[1:] if score - s < 0.02]
        if close:
            options = "; ".join(f.content for f in [best, *close])
            return ToolResult.failure(f"Achei mais de uma: {options}. Qual delas?")
        await self._drop([best.id])
        return ToolResult.success(f"Esqueci: {best.content}.", say="Pronto, esqueci.")

    async def delete(self, fact_id: str) -> int:
        """Apaga uma memória pelo id (painel)."""
        return await self._drop([fact_id])

    async def forget_all(self) -> ToolResult:
        removed = await self._drop([f.id for f in await self._store.all()])
        word = "memória" if removed == 1 else "memórias"
        return ToolResult.success(f"Apaguei {removed} {word}.")

    async def list(self) -> ToolResult:
        facts = await self._store.all()
        if not facts:
            return ToolResult.success("Ainda não guardei nada sobre você.")
        listed = "; ".join(f.content for f in facts[:10])
        more = f" (e mais {len(facts) - 10})" if len(facts) > 10 else ""
        count = "uma coisa" if len(facts) == 1 else f"{len(facts)} coisas"
        return ToolResult.success(f"Sei {count}: {listed}{more}.")

    # ------------------------------------------------------------------ busca

    async def search(
        self, query: str, *, limit: int = 3, min_score: float | None = None
    ) -> list[tuple[MemoryFact, float]]:
        if not query.strip():
            return []
        vector = (await self._embedder.embed([query], query=True))[0]
        threshold = self._min_score if min_score is None else min_score
        await self._refresh()
        return [
            (self._facts[key], score)
            for key, score in self._index.search(vector, limit)
            if score >= threshold
        ]

    async def relevant(self, text: str) -> Sequence[str]:
        """Porta ``MemoryRecall``: fatos que ajudam a responder ``text``, para o contexto."""
        found = await self.search(text, limit=self._max)
        if found:
            await self._store.touch([f.id for f, _ in found], self._clock.now())
        return [f.content for f, _ in found]

    # ------------------------------------------------------------------ índice

    async def _refresh(self) -> None:
        """Carrega fatos e vetores na primeira vez, ou de novo se outro processo mexeu no banco."""
        revision = await self._store.revision()
        if revision == self._revision:
            return
        facts = await self._store.all()
        known = await self._store.vectors(self._embedder.name)
        missing = [f for f in facts if f.id not in known]
        if missing:  # fatos antigos ou de outro modelo de embedding
            vectors = await self._embedder.embed([f.content for f in missing], query=False)
            fresh = list(zip((f.id for f in missing), vectors, strict=True))
            await self._store.set_vectors(fresh, self._embedder.name)
            known.update(fresh)
        self._facts = {f.id: f for f in facts}
        self._index.clear()
        for fact in facts:
            self._index.add(fact.id, known[fact.id])
        self._revision = revision

    async def _drop(self, fact_ids: Sequence[str]) -> int:
        removed = await self._store.delete(fact_ids)
        for fact_id in fact_ids:
            self._facts.pop(fact_id, None)
            self._index.remove(fact_id)
        return removed
