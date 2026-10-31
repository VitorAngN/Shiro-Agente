"""Modo texto: conversa com a SHIRO pelo terminal (``shiro chat``).

Na Fase 1 é a forma de usar e depurar o agente antes da voz (marco 1b).
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import TextIO

from shiro.core.models import AgentResult, CallOutcome, DecisionKind, Tier
from shiro.core.ports import LLMError
from shiro.interfaces.theme import Theme

_YES = {"s", "sim", "y", "yes", "confirmo", "pode"}
_EXIT = {"sair", "exit", "quit", "tchau"}

type Reader = Callable[[str], str]


class CliConfirmation:
    """Confirmação pelo teclado. No terminal, digitar já é uma confirmação física."""

    def __init__(self, reader: Reader = input, theme: Theme | None = None) -> None:
        self._reader = reader
        self._theme = theme or Theme(color=False)

    async def ask(self, prompt: str, kind: DecisionKind) -> bool:
        label = "confirmação física: " if kind is DecisionKind.CONFIRM_PHYSICAL else ""
        try:
            answer = await asyncio.to_thread(self._reader, self._theme.confirm(f"{label}{prompt}"))
        except EOFError:
            return False
        return answer.strip().casefold() in _YES


def describe_result(result: AgentResult) -> str:
    """Linha de diagnóstico: camada, modelo, tempo e ferramentas."""
    source = "regra" if result.tier is Tier.T0 else f"{result.provider}/{result.model}"
    seconds = f"{result.latency_ms / 1000:.2f}".replace(".", ",")
    parts = [result.tier.value, source, f"{seconds} s"]
    for executed in result.calls:
        if executed.outcome in {CallOutcome.BLOCKED, CallOutcome.DENIED}:
            mark = "⊘"
        else:
            mark = "✓" if executed.result.ok else "✗"
        parts.append(f"{executed.call.name} {mark}")
    if result.claim_blocked:
        parts.append("ação alegada bloqueada")
    return "[" + " · ".join(parts) + "]"


def use_safe_output() -> None:
    """Evita erro de codificação em consoles antigos do Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


class TextSession:
    def __init__(
        self,
        run_turn: Callable[[str], Awaitable[AgentResult]],
        *,
        name: str,
        verbose: bool,
        out: TextIO | None = None,
        reader: Reader = input,
        theme: Theme | None = None,
    ) -> None:
        self._run_turn = run_turn
        self._name = name
        self._verbose = verbose
        self._out = out or sys.stdout
        self._reader = reader
        self.theme = theme or Theme(color=False)

    def print(self, text: str) -> None:
        print(text, file=self._out, flush=True)

    async def send(self, text: str) -> AgentResult:
        result = await self._run_turn(text)
        self.print(self.theme.assistant(self._name, result.text))
        if self._verbose:
            self.print(self.theme.meta(describe_result(result)))
        return result

    async def loop(self) -> None:
        self.print(self.theme.paint("Digite sua mensagem. 'sair' encerra.", (154, 163, 178)))
        while True:
            try:
                text = (await asyncio.to_thread(self._reader, self.theme.user_prompt())).strip()
            except (EOFError, KeyboardInterrupt):
                self.print("")
                return
            if not text:
                continue
            if text.casefold() in _EXIT:
                return
            await self.send(text)


def llm_down_message(host: str, error: LLMError) -> str:
    return (
        f"modelo local offline: o Ollama não respondeu em {host}. Ele está aberto?\n"
        f"       detalhe: {error}\n"
        "       Volume, mídia, apps, hora e clima continuam funcionando."
    )
