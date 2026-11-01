"""Dublês de teste para as portas do núcleo."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from shiro.core.models import (
    CompletionRequest,
    CompletionResponse,
    DecisionKind,
    RiskLevel,
    ToolCall,
    ToolResult,
    Usage,
)
from shiro.core.ports import LLMError, ToolContext, ToolSpec

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def reply(text: str = "", *calls: tuple[str, dict[str, Any]]) -> CompletionResponse:
    """Resposta roteirizada: texto final ou chamadas de ferramenta."""
    return CompletionResponse(
        provider="fake",
        model="fake-1",
        text=text,
        tool_calls=tuple(
            ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls)
        ),
        usage=Usage(prompt_tokens=10, completion_tokens=5),
    )


class FakeProvider:
    def __init__(
        self,
        script: Sequence[CompletionResponse | Exception],
        *,
        name: str = "fake",
        model: str = "fake-1",
    ) -> None:
        self._script = list(script)
        self._name = name
        self._model = model
        self.requests: list[CompletionRequest] = []
        self.warmed: list[CompletionRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if not self._script:
            raise LLMError("roteiro do teste acabou")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def warm_up(self, request: CompletionRequest) -> None:
        self.warmed.append(request)


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int = Field(ge=0, le=100)


class LevelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=0, le=100)


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FakeTool:
    """Ferramenta configurável que registra as chamadas recebidas."""

    def __init__(
        self,
        name: str,
        *,
        risk: RiskLevel = RiskLevel.R1,
        args_model: type[BaseModel] = EchoArgs,
        result: ToolResult | Callable[[BaseModel], ToolResult] | Exception | None = None,
        output_trusted: bool = True,
        local_only: bool = False,
        timeout_s: float = 10.0,
        group: str = "core",
    ) -> None:
        self._spec = ToolSpec(
            name=name,
            description=f"Ferramenta de teste {name}.",
            args_model=args_model,
            risk=risk,
            output_trusted=output_trusted,
            local_only=local_only,
            timeout_s=timeout_s,
            group=group,
        )
        self._result = result
        self.calls: list[BaseModel] = []

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def describe(self, args: BaseModel) -> str:
        return f"executar {self._spec.name} com {args.model_dump()}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        del ctx
        self.calls.append(args)
        if isinstance(self._result, Exception):
            raise self._result
        if callable(self._result):
            return self._result(args)
        return self._result or ToolResult.success(f"{self._spec.name} ok", say="Feito.")


class FakeConfirmation:
    def __init__(self, answers: Sequence[bool] = ()) -> None:
        self._answers = list(answers)
        self.prompts: list[tuple[str, DecisionKind]] = []

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        self.prompts.append((prompt, kind))
        return self._answers.pop(0) if self._answers else False


class MemoryAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def record(self, event_type: str, trace_id: str, payload: Mapping[str, Any]) -> None:
        self.events.append((event_type, trace_id, dict(payload)))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [payload for kind, _, payload in self.events if kind == event_type]


class FixedClock:
    def __init__(self, now: datetime | None = None) -> None:
        self._now = now or datetime(2026, 10, 31, 17, 5, tzinfo=SAO_PAULO)

    def now(self) -> datetime:
        return self._now
