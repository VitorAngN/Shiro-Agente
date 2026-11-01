"""Memória de longo prazo (RF-41 a RF-44): guardar, achar, esquecer e nunca sair do PC."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from shiro.app import Desktop, build_app
from shiro.core.context import ContextBuilder
from shiro.core.models import Role, Tier
from shiro.downloads import COMPLETE_MARK
from shiro.memory.embedding import HashingEmbedder, OnnxEmbedder
from shiro.memory.rules import MemoryRules
from shiro.memory.service import MemoryService, categorize, is_sensitive
from shiro.memory.setup import build_embedder, embedding_dir
from shiro.persistence.database import Database
from shiro.persistence.memory import SqliteMemoryStore
from shiro.settings import MemorySettings, Settings
from tests.fakes import SAO_PAULO, FakeProvider, reply
from tests.unit.test_activities import MovableClock
from tests.unit.test_tools import FakeProbe

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


rules = MemoryRules(lambda: NOW)


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("lembra que eu torço pro Coritiba", ("remember_fact", {"text": "eu torço pro Coritiba"})),
        (
            "Shiro, guarda que minha irmã se chama Ana",
            ("remember_fact", {"text": "minha irmã se chama Ana"}),
        ),
        ("esquece que eu gosto de café", ("forget_fact", {"query": "eu gosto de café"})),
        ("esquece o que eu falei sobre a Ana", ("forget_fact", {"query": "a Ana"})),
        ("esquece tudo", ("forget_all_memories", {})),
        (
            "lembra que eu prefiro reuniões de manhã",  # parte do dia não é prazo
            ("remember_fact", {"text": "eu prefiro reuniões de manhã"}),
        ),
        ("o que você sabe sobre mim?", ("list_memories", {})),
    ],
)
def test_memory_rules(spoken: str, expected: tuple[str, dict[str, object]]) -> None:
    assert rules(spoken) == [expected]


@pytest.mark.parametrize(
    "spoken",
    [
        "lembra que tenho prova amanhã às 8h",  # tem prazo: atividade, não memória
        "me lembra de tirar a roupa do varal",  # lembrete
        "você lembra de mim?",
        "abre o spotify",
    ],
)
def test_memory_rules_leave_other_things_alone(spoken: str) -> None:
    assert rules(spoken) is None


def test_memories_go_after_the_cached_prefix() -> None:
    builder = ContextBuilder(assistant_name="Shiro")
    plain = builder.build([], "oi")
    with_memory = builder.build([], "qual meu time?", ["eu torço pro Coritiba"])
    assert with_memory[0] == plain[0]  # a persona (prefixo em cache) não muda
    assert with_memory[1].role is Role.SYSTEM and "Coritiba" in with_memory[1].content
    assert with_memory[-1].content == "qual meu time?"


async def test_agent_uses_memories_and_keeps_them_local(tmp_path: Path) -> None:
    local = FakeProvider([reply("Você torce pro Coritiba.")])
    cloud = FakeProvider([reply("não deveria ser chamado")], name="gemini")
    settings = Settings.model_validate({"policy": {"read_only_mode": False}})
    app = await build_app(
        settings,
        confirmation=type("No", (), {"ask": staticmethod(lambda *_: _false())})(),  # type: ignore[arg-type]
        database_path=":memory:",
        data_dir=tmp_path,
        desktop=Desktop(),
        local_llm=local,
        cloud_llm=cloud,
        probe=FakeProbe(),
    )
    try:
        saved = await app.agent.run_turn("lembra que eu torço pro Coritiba")
        assert saved.tier is Tier.T0 and saved.calls[0].result.ok
        answer = await app.agent.run_turn("pra qual time do Coritiba eu torço?")
        assert answer.tier is Tier.T1
        request = local.requests[0]
        assert any(m.role is Role.SYSTEM and "Coritiba" in m.content for m in request.messages[1:])
        assert cloud.requests == []
    finally:
        await app.aclose()


async def _false() -> bool:
    return False


class FakeTokenizer:
    def encode_batch(self, texts: list[str]) -> list[Any]:
        width = max(len(t.split()) for t in texts)
        return [
            type(
                "E",
                (),
                {
                    "ids": [len(w) for w in t.split()] + [1] * (width - len(t.split())),
                    "attention_mask": [1] * len(t.split()) + [0] * (width - len(t.split())),
                },
            )()
            for t in texts
        ]


class FakeSession:
    def __init__(self) -> None:
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, _: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        ids = feed["input_ids"].astype(np.float32)
        return [np.stack([ids, ids * 0 + 1, ids * 2], axis=-1)]


async def test_e5_embedder_pools_and_prefixes(tmp_path: Path) -> None:
    embedder = OnnxEmbedder(
        model=tmp_path / "m.onnx",
        tokenizer=tmp_path / "t.json",
        label="e5",
        query_prefix="query: ",
        relevant_score=0.83,
    )
    session = FakeSession()

    def fake_load() -> None:
        embedder._tokenizer, embedder._session = FakeTokenizer(), session  # pyright: ignore[reportPrivateUsage]
        embedder._inputs = {"input_ids", "attention_mask", "token_type_ids"}  # pyright: ignore[reportPrivateUsage]

    embedder._load = fake_load  # type: ignore[method-assign]
    vectors = await embedder.embed(["oi", "tudo bem por aí"], query=True)

    assert vectors.shape == (2, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert "token_type_ids" in session.feeds[0]
    assert embedder.name == "onnx:e5" and embedder.relevant_score == 0.83


def test_build_embedder_falls_back_without_the_model(tmp_path: Path) -> None:
    settings = MemorySettings()
    assert isinstance(build_embedder(settings, tmp_path), HashingEmbedder)
    folder = embedding_dir(tmp_path, settings.embedding_model)
    folder.mkdir(parents=True)
    (folder / COMPLETE_MARK).write_text("ok")
    assert isinstance(build_embedder(settings, tmp_path), OnnxEmbedder)
    old_style = MemorySettings(embedding_model="nomic-embed-text")  # nome do Ollama, sem "/"
    assert isinstance(build_embedder(old_style, tmp_path), HashingEmbedder)
