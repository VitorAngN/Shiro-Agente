"""Memória de longo prazo (RF-41 a RF-44): guardar, achar, esquecer e recusar segredos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from shiro.application.memory.service import MemoryService, categorize, is_sensitive
from shiro.domain.memory.embedding import HashingEmbedder
from shiro.infrastructure.persistence.database import Database
from shiro.infrastructure.persistence.memory import SqliteMemoryStore
from tests.fakes.agent import SAO_PAULO
from tests.fakes.clock import MovableClock

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)


@pytest.fixture
async def memory() -> Any:
    database = await Database.open(":memory:")
    service = MemoryService(
        store=SqliteMemoryStore(database), embedder=HashingEmbedder(), clock=MovableClock(NOW)
    )
    yield service
    await database.close()


async def test_remember_list_and_dedupe(memory: MemoryService) -> None:
    assert (await memory.list()).content == "Ainda não guardei nada sobre você."
    saved = await memory.remember("eu torço pro Coritiba.")
    assert saved.ok and saved.say == "Guardado."
    await memory.remember("meu café preferido é o coado, sem açúcar")
    again = await memory.remember("Eu torço pro Coritiba")
    assert again.say == "Já sei disso."
    listed = await memory.list()
    assert listed.content.startswith("Sei 2 coisas:")
    assert "eu torço pro Coritiba" in listed.content


@pytest.mark.parametrize(
    "secret",
    [
        "minha senha do banco é abacaxi123",
        "meu CPF é 123.456.789-00",
        "o token do github é ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "o número do cartão é 4111 1111 1111 1111",
        "a chave de api do gemini",
    ],
)
async def test_secrets_are_never_stored(memory: MemoryService, secret: str) -> None:
    refused = await memory.remember(secret)
    assert not refused.ok and "não guardo senhas" in refused.content
    assert (await memory.list()).content == "Ainda não guardei nada sobre você."


def test_sensitive_and_categories() -> None:
    assert not is_sensitive("eu prefiro reunião de manhã")
    assert categorize("eu prefiro café coado") == "preferencia"
    assert categorize("minha irmã se chama Ana") == "pessoa"
    assert categorize("meu TCC é sobre visão computacional") == "projeto"
    assert categorize("eu moro perto do centro") == "outro"


async def test_relevant_memories_and_forgetting(memory: MemoryService) -> None:
    await memory.remember("eu torço pro Coritiba")
    await memory.remember("meu café preferido é o coado")
    await memory.remember("minha irmã se chama Ana")

    assert await memory.relevant("qual o melhor café pra hoje?") == ["meu café preferido é o coado"]
    assert await memory.relevant("abre o spotify") == []

    missing = await memory.forget("fórmula 1")
    assert not missing.ok and "Não achei" in missing.content
    done = await memory.forget("o café")
    assert done.ok and "coado" in done.content
    assert await memory.relevant("café") == []
    cleared = await memory.forget_all()
    assert cleared.content == "Apaguei 2 memórias."


async def test_ambiguous_forget_asks_which(memory: MemoryService) -> None:
    await memory.remember("gosto de café coado")
    await memory.remember("gosto de café gelado")
    answer = await memory.forget("gosto de café")
    assert not answer.ok and "Qual delas?" in answer.content


async def test_refusals_and_limits(memory: MemoryService) -> None:
    assert not (await memory.remember("   ")).ok
    assert "resumir" in (await memory.remember("x" * 400)).content
    assert await memory.search("   ") == []


async def test_reindexes_when_the_embedding_model_changes() -> None:
    database = await Database.open(":memory:")
    store = SqliteMemoryStore(database)
    old = MemoryService(store=store, embedder=HashingEmbedder(256), clock=MovableClock(NOW))
    await old.remember("eu torço pro Coritiba")
    new = MemoryService(store=store, embedder=HashingEmbedder(512), clock=MovableClock(NOW))
    assert await new.relevant("Coritiba") == ["eu torço pro Coritiba"]
    # Um vetor por fato: o do modelo novo substitui o antigo.
    assert len(await store.vectors("hash-v1-512")) == 1
    assert await store.vectors("hash-v1-256") == {}
    facts = await store.all()
    assert facts[0].last_used_at is not None  # usar a memória atualiza o "visto por último"
    assert await store.delete([]) == 0
    await database.close()


async def test_reloads_when_another_process_changes_the_database(tmp_path: Path) -> None:
    """O painel (outro processo) apagou uma memória: a bandeja não pode mais usá-la."""
    file = tmp_path / "shiro.db"
    mine, theirs = await Database.open(file), await Database.open(file)
    service = MemoryService(
        store=SqliteMemoryStore(mine), embedder=HashingEmbedder(), clock=MovableClock(NOW)
    )
    await service.remember("eu torço pro Coritiba")
    assert await service.relevant("Coritiba") == ["eu torço pro Coritiba"]
    other = SqliteMemoryStore(theirs)
    (fact,) = await other.all()
    assert await other.delete([fact.id]) == 1
    assert await service.relevant("Coritiba") == []
    await mine.close()
    await theirs.close()
