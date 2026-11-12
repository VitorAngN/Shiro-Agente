"""Roteador de intenções: Tier 0 por regras e escolha entre Tier 1 e Tier 2 (ADR-0003).

O Tier 0 resolve, sem LLM, os comandos frequentes e previsíveis. A gramática é
deliberadamente estrita: na dúvida, o pedido vai para o modelo.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from shiro.domain.models import ToolCall
from shiro.domain.text import normalize, parse_number, similarity, sound_key

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

# "apra" e "habra": o Whisper às vezes troca ou acrescenta letras no começo da frase.
_OPEN = re.compile(r"^(?:abre|abra|apra|habra|abrir|inicia|inicie|executa|execute)\s+(?P<apps>.+)$")
_CLOSE = re.compile(r"^(?:fecha|feche|fechar|encerra|encerre)\s+(?P<apps>.+)$")
_SOUND_MATCH = 0.75  # parecido o bastante com o nome de um app
_SOUND_MARGIN = 0.15  # e claramente mais parecido que o segundo colocado
_APP_SEPARATOR = re.compile(r"\s+e\s+|\s*,\s*")
_ARTICLE = re.compile(r"^(?:o|a|os|as)\s+")

_WEATHER = re.compile(
    r"^(?:como (?:esta|ta) o (?:tempo|clima)(?: hoje| agora| la fora)?"
    r"|qual (?:e )?o clima(?: hoje| agora)?"
    r"|(?:qual (?:e )?a )?previsao(?: do tempo)?(?: (?:pra|para|de) hoje)?"
    r"|vai chover(?: hoje)?|ta (?:frio|calor)(?: la fora)?|clima)$"
)

# "terminei o trabalho de cálculo" (ADR-0011: ação garantida pela regra, não pelo modelo).
# "acabei de ..." fica de fora: quer dizer "acabei de fazer agora", não "concluí".
_OFF_THE_LIST = r"(?:\s+(?:pode\s+)?(?:tirar|tira|remover|remove|riscar|risca)\s+da lista)?"
_COMPLETE = re.compile(
    r"^(?:ja\s+)?(?:terminei|conclui|finalizei|entreguei|acabei(?! de\b)"
    r"|dei conta d(?:e|o|a|os|as|aquele|aquela|aqueles|aquelas|esse|essa))"
    r"\s+(?P<q>.+?)" + _OFF_THE_LIST + r"$"
    r"|^ja fiz\s+(?P<q3>.+?)" + _OFF_THE_LIST + r"$"
    r"|^(?:pode\s+)?(?:risca|riscar|risque|da baixa (?:n[oa]|em))\s+(?P<q4>.+?)"
    r"(?:\s+(?:que\s+)?(?:eu\s+)?ja\s+(?:fiz|terminei|entreguei|acabei))?$"
    # "tira X das pendentes, essa eu já entreguei"
    r"|^(?:pode\s+)?(?:tirar|tira|remover|remove)\s+(?P<q5>.+?)\s+(?:das pendentes|da lista)"
    r"(?:\s+(?:que|essa|esse|pois|porque)?\s*(?:eu\s+)?ja\s+(?:fiz|terminei|entreguei|acabei))?$"
    r"|^(?:marca|marque|pode marcar)\s+(?P<q2>.+?)\s+como\s+"
    r"(?:concluid[oa]|feit[oa]|pronto|pronta)$"
)
# "aquela prova de física já era, pode considerar feita"
_DONE_STATE = re.compile(
    r"^(?:(?:aquel[ea]s?|ess[ea]s?|est[ea]s?|o|a|os|as)\s+)?(?P<q>(?:\S+\s+){0,7}?\S+)\s+"
    r"(?:ja era|ja foi|(?:ja\s+)?(?:ta|esta) (?:feit[oa]|pront[oa]|entregue))"
    r"(?:\s+(?:pode\s+)?(?:considerar|considera|marcar|marca|tirar|tira)\s+(?:como\s+)?"
    r"(?:feit[oa]|concluid[oa]|pront[oa]|da lista))?$"
)
_PERIODS = {
    "hoje": "today",
    "amanha": "tomorrow",
    "essa semana": "this_week",
    "esta semana": "this_week",
    "nessa semana": "this_week",
    "nesta semana": "this_week",
    "semana que vem": "next_week",
    "na semana que vem": "next_week",
    "pra semana que vem": "next_week",
    "atrasado": "overdue",
    "atrasada": "overdue",
    "atrasados": "overdue",
    "atrasadas": "overdue",
}
_PERIOD_WORDS = "|".join(sorted(_PERIODS, key=len, reverse=True))
_LIST = re.compile(
    r"^(?:o que|oque) (?:eu )?tenho(?: (?:pra fazer|de atividade|de atividades))?"
    rf"(?: (?P<p1>{_PERIOD_WORDS}))?$"
    r"|^(?:quais (?:sao )?)?(?:as )?minhas atividades"
    rf"(?: (?:de |pra |para )?(?P<p2>{_PERIOD_WORDS}))?$"
    r"|^tenho (?:alguma coisa|algo|alguma atividade|atividade)(?: pra fazer)?"
    rf" (?P<p3>{_PERIOD_WORDS})$"
    r"|^(?:o que|oque) (?:esta|ta) (?P<p4>atrasado|atrasada|atrasados|atrasadas)$"
)

_THEN = re.compile(r"\s+(?:e\s+depois|e\s+entao|depois|e)\s+")
_MAX_PARTS = 5

type Tier0Calls = Sequence[tuple[str, Mapping[str, object]]]
type Tier0Rule = Callable[[str], Tier0Calls | None]
"""Regra extra do Tier 0, plugada pela composição; recebe o texto original."""

_TIME = re.compile(
    r"^(?:que horas sao|que hora e|que horas e|que dia e hoje|qual a data de hoje|que dia e)$"
)


class IntentRouter:
    """Decide entre Tier 0, Tier 1 e Tier 2.

    Args:
        apps: chave do app → apelidos falados (ex.: ``{"vscode": ["vs code", "code"]}``).
        cloud_triggers: expressões que pedem a nuvem explicitamente ("pensa bem").
        rules: regras extras, testadas depois das embutidas (ex.: criar atividade, ADR-0014).
        teaching: regras que olham o texto como foi falado, antes das lições ("quando eu
            disser X, faça Y", ADR-0023).
        expand: troca as expressões que o usuário ensinou pelo significado delas.
    """

    def __init__(
        self,
        *,
        apps: Mapping[str, Sequence[str]],
        cloud_triggers: Sequence[str],
        rules: Sequence[Tier0Rule] = (),
        teaching: Sequence[Tier0Rule] = (),
        expand: Callable[[str], str] | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._teaching = tuple(teaching)
        self._expand = expand
        self._aliases: dict[str, str] = {}
        self._sounds: dict[str, str] = {}  # chave de pronúncia → app
        for key, aliases in apps.items():
            for alias in (key, *aliases):
                self.teach_alias(alias, key)
        self._cloud_triggers = tuple(normalize(t) for t in cloud_triggers if t.strip())

    def teach_alias(self, alias: str, key: str) -> None:
        """Mais um jeito de chamar o app ``key`` (configurado ou ensinado pelo usuário)."""
        self._aliases[normalize(alias)] = key
        if sound := sound_key(alias):
            self._sounds[sound] = key

    def rewrite(self, text: str) -> str:
        """O pedido com as expressões ensinadas trocadas pelo significado (ADR-0023).

        Quem está ensinando ou desaprendendo fala a expressão crua: aí nada é trocado.
        """
        if self._expand is None or any(rule(text) is not None for rule in self._teaching):
            return text
        return self._expand(text)

    def match_tier0(self, text: str) -> tuple[ToolCall, ...] | None:
        """Chamadas de ferramenta para o pedido, ou ``None`` se não for Tier 0."""
        calls: Tier0Calls | None = None
        for rule in self._teaching:
            calls = rule(text)
            if calls is not None:
                break
        if calls is None:
            text = self.rewrite(text)
            calls = self._single(text) or self._sequence(text)
        if calls is None:
            return None
        return tuple(
            ToolCall(id=f"t0_{i}", name=name, arguments=dict(args))
            for i, (name, args) in enumerate(calls)
        )

    def _single(self, text: str) -> Tier0Calls | None:
        command = self._clean(text)
        if not command:
            return None
        calls: Tier0Calls | None = self._match(command)
        for rule in self._rules:
            if calls is not None:
                break
            calls = rule(text)
        return calls

    def _sequence(self, text: str) -> Tier0Calls | None:
        """ "feche o discord e abra a steam": só vale se cada parte for um comando conhecido."""
        parts = [part for part in _THEN.split(self._clean(text)) if part]
        if not 2 <= len(parts) <= _MAX_PARTS:
            return None
        calls: list[tuple[str, Mapping[str, object]]] = []
        for part in parts:
            found = self._single(part)
            if found is None:
                return None
            calls.extend(found)
        return calls

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
        if match := _COMPLETE.match(command):
            query = (
                match["q"] or match["q2"] or match["q3"] or match["q4"] or match["q5"] or ""
            ).strip()
            return [("complete_activity", {"query": query})] if query else None
        if match := _DONE_STATE.match(command):
            return [("complete_activity", {"query": match["q"]})]
        if match := _LIST.match(command):
            spoken = match["p1"] or match["p2"] or match["p3"] or match["p4"]
            return [("list_activities", {"period": _PERIODS.get(spoken or "", "all")})]
        if _WEATHER.match(command):
            return [("get_weather", {})]
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
            name = _ARTICLE.sub("", part.strip())
            key = self._aliases.get(name) or self._sounds_like(name)
            if key is None:
                return None
            if key not in keys:
                keys.append(key)
        return keys or None

    def _sounds_like(self, name: str) -> str | None:
        """O app cujo nome soa parecido ("crome" → chrome), só se não houver dúvida."""
        sound = sound_key(name)
        if len(sound) < 3:
            return None
        scored = sorted(
            ((similarity(sound, known), key) for known, key in self._sounds.items()),
            reverse=True,
        )
        if not scored or scored[0][0] < _SOUND_MATCH:
            return None
        best, key = scored[0]
        rivals = [s for s, k in scored[1:] if k != key]
        if rivals and best - rivals[0] < _SOUND_MARGIN:
            return None
        return key
