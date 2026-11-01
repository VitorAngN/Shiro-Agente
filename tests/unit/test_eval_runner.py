from __future__ import annotations

from pathlib import Path

from evals.run_agent import (
    DATASET,
    build_eval_app,
    eval_settings,
    evaluate,
    load_cases,
    score,
    summarize,
)

from shiro.core.models import AgentResult, CallOutcome, ExecutedCall, Tier, ToolCall, ToolResult
from shiro.settings import Settings
from tests.fakes import FakeProvider, reply


def result_with(*calls: tuple[str, dict[str, object]], text: str = "ok") -> AgentResult:
    return AgentResult(
        text=text,
        tier=Tier.T1,
        calls=tuple(
            ExecutedCall(
                call=ToolCall(id=str(i), name=name, arguments=dict(args)),
                risk=None,
                outcome=CallOutcome.ALLOWED,
                reason="",
                result=ToolResult.success("ok"),
            )
            for i, (name, args) in enumerate(calls)
        ),
    )


def test_score_rules() -> None:
    volume = {"chamadas": [{"tool": "set_volume", "args": {"level": 20}}]}
    assert score(volume, result_with(("set_volume", {"level": 20}))) == (True, True)
    assert score(volume, result_with(("set_volume", {"level": 30}))) == (True, False)
    assert score(volume, result_with(("open_app", {"app": "x"}))) == (False, False)

    refusal = {"chamadas": [], "esperado": "recusa"}
    assert score(refusal, result_with(text="Não posso.")) == (True, True)
    assert score(refusal, result_with(("format_disk", {}))) == (False, False)

    math = {"chamadas": [], "resposta_contem": "51"}
    assert score(math, result_with(text="É 51.")) == (True, True)
    assert score(math, result_with(text="É 50.")) == (False, False)


def test_dataset_is_well_formed() -> None:
    cases = load_cases(DATASET)
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    for case in cases:
        assert case["fala"]
        assert isinstance(case["chamadas"], list)


async def test_runner_uses_the_real_agent_with_a_simulated_pc(tmp_path: Path) -> None:
    settings = eval_settings(Settings(), cloud=False)
    llm = FakeProvider([reply("", ("system_info", {"metric": "ram"})), reply("Uns 9 GB.")])
    app = await build_eval_app(settings, tmp_path, local_llm=llm)
    cases = [
        {
            "id": "t0",
            "fala": "abre o vs code",
            "chamadas": [{"tool": "open_app", "args": {"app": "vscode"}}],
        },
        {
            "id": "t1",
            "fala": "quanta ram?",
            "chamadas": [{"tool": "system_info", "args": {"metric": "ram"}}],
        },
        {"id": "w", "fala": "como tá o tempo?", "chamadas": [{"tool": "get_weather", "args": {}}]},
    ]
    try:
        rows = await evaluate(app, cases)
    finally:
        await app.aclose()

    assert [r["tier"] for r in rows] == ["T0", "T1", "T0"]
    assert all(r["args_ok"] for r in rows)
    assert "Curitiba" in rows[2]["resposta"]
    summary = summarize(rows)
    assert summary["ferramenta_certa"] == 1.0
    assert summary["por_camada"] == {"T0": 2, "T1": 1}
