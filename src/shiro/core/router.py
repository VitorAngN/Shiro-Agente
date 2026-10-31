"""Roteador de intenções: Tier 0 por regras e escolha entre Tier 1 e Tier 2 (ADR-0003).

O Tier 0 resolve, sem LLM, os comandos frequentes e previsíveis. A gramática é
deliberadamente estrita: na dúvida, o pedido vai para o modelo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from shiro.core.models import ToolCall
from shiro.core.text import normalize, parse_number

_WAKE_PREFIX = re.compile(r"^(?:(?:ei|ok|hey|oi)\s+)?shiro\s+")
_POLITE_SUFFIX = re.compile(r"\s+(?:por favor|pf|pfv)$")

_VOLUME_SET = re.compile(
    r"^(?:(?:coloca|deixa|poe|bota|muda|ajusta|define|abaixa|baixa|aumenta|sobe|diminui)\s+)?"
    r"(?:o\s+)?(?:volume|som)\s+(?:(?:em|pra|para|no|a)\s+)?(?P<n>[a-z0-9 ]+?)"
    r"(?:\s*%|\s+por cento)?$"
)
_VOLUME_UP = re.compile(r"^(?:aumenta|sobe)\s+(?:o\s+)?(?:volume|som)(?:\s+um pouco)?$")
_VOLUME_DOWN = re.compile(r"^(?:abaixa|baixa|diminui)\s+(?:o\s+)?(?:volume|som)(?:\s+um pouco)?$")

_MEDIA = (
    (
        "play",
        re.compile(
            r"^(?:toca|continua|play|despausa|retoma|volta a tocar)"
            r"(?:\s+(?:a|o))?(?:\s+(?:musica|som|video|midia))?$"
        ),
    ),
    (
        "pause",
        re.compile(r"^(?:pausa|pause|para)(?:\s+(?:a|o))?(?:\s+(?:musica|som|video|midia))?$"),
    ),
    (
        "next",
        re.compile(
            r"^(?:pula|passa|avanca|proxima)(?:\s+(?:essa|esta|a|pra|para))?"
            r"(?:\s+(?:musica|faixa|proxima))?$"
        ),
    ),
    (
        "previous",
        re.compile(
            r"^(?:volta|anterior|musica anterior|faixa anterior)(?:\s+(?:a|pra|para))?"
            r"(?:\s+(?:musica|faixa|anterior))?$"
        ),
    ),
)

_OPEN = re.compile(r"^(?:abre|abra|abrir|inicia|executa)\s+(?P<apps>.+)$")
_CLOSE = re.compile(r"^(?:fecha|feche|fechar|encerra)\s+(?P<apps>.+)$")
_APP_SEPARATOR = re.compile(r"\s+e\s+|\s*,\s*")
_ARTICLE = re.compile(r"^(?:o|a|os|as)\s+")

_TIME = re.compile(
    r"^(?:que horas sao|que hora e|que horas e|que dia e hoje|qual a data de hoje|que dia e)$"
)


class IntentRouter:
    """Decide entre Tier 0, Tier 1 e Tier 2.

    Args:
        apps: chave do app → apelidos falados (ex.: ``{"vscode": ["vs code", "code"]}``).
        cloud_triggers: expressões que pedem a nuvem explicitamente ("pensa bem").
    """

    def __init__(self, *, apps: Mapping[str, Sequence[str]], cloud_triggers: Sequence[str]) -> None:
        self._aliases: dict[str, str] = {}
        for key, aliases in apps.items():
            for alias in (key, *aliases):
                self._aliases[normalize(alias)] = key
        self._cloud_triggers = tuple(normalize(t) for t in cloud_triggers if t.strip())

    def match_tier0(self, text: str) -> tuple[ToolCall, ...] | None:
        """Chamadas de ferramenta para o pedido, ou ``None`` se não for Tier 0."""
        command = self._clean(text)
        if not command:
            return None
        calls = self._match(command)
        if calls is None:
            return None
        return tuple(
            ToolCall(id=f"t0_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(calls)
        )

    def wants_cloud(self, text: str) -> bool:
        command = normalize(text)
        return any(trigger in command for trigger in self._cloud_triggers)

    @staticmethod
    def _clean(text: str) -> str:
        command = normalize(text)
        command = _WAKE_PREFIX.sub("", command)
        return _POLITE_SUFFIX.sub("", command).strip()

    def _match(self, command: str) -> list[tuple[str, dict[str, object]]] | None:
        if _VOLUME_UP.match(command):
            return [("change_volume", {"delta": 10})]
        if _VOLUME_DOWN.match(command):
            return [("change_volume", {"delta": -10})]
        if match := _VOLUME_SET.match(command):
            level = parse_number(match["n"])
            if level is not None and 0 <= level <= 100:
                return [("set_volume", {"level": level})]
            return None
        for action, pattern in _MEDIA:
            if pattern.match(command):
                return [("media_control", {"action": action})]
        if _TIME.match(command):
            return [("get_time", {})]
        for tool, pattern in (("open_app", _OPEN), ("close_app", _CLOSE)):
            if match := pattern.match(command):
                apps = self._resolve_apps(match["apps"])
                return [(tool, {"app": app}) for app in apps] if apps else None
        return None

    def _resolve_apps(self, spoken: str) -> list[str] | None:
        keys: list[str] = []
        for part in _APP_SEPARATOR.split(spoken):
            key = self._aliases.get(_ARTICLE.sub("", part.strip()))
            if key is None:
                return None
            if key not in keys:
                keys.append(key)
        return keys or None
