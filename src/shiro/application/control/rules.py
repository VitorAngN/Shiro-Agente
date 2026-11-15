"""Tier 0 dos sites: "abre o YouTube", "pesquisa hollow knight no YouTube" (ADR-0024).

Sem passar pelo modelo: o pedido vira ``open_url`` na hora. Os nomes em
inglês são comparados pela pronúncia (``sound_key``), então "iutubi" e
"guitrub" também valem. Pedidos que não batem ficam para o modelo.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from shiro.domain.text import normalize, similarity, sound_key

type Calls = list[tuple[str, dict[str, object]]]


@dataclass(frozen=True)
class Site:
    key: str
    label: str
    url: str
    aliases: tuple[str, ...] = ()
    search: bool = False
    """Tem busca própria (``open_url`` com ``on=key``)."""


SITES: tuple[Site, ...] = (
    Site("youtube", "YouTube", "youtube.com", ("iutubi", "iutube", "yutube", "you tube"), True),
    Site("google", "Google", "google.com", ("gugou", "gugol"), True),
    Site("wikipedia", "Wikipedia", "pt.wikipedia.org", ("wiki", "uiquipedia"), True),
    Site("github", "GitHub", "github.com", ("guitrub", "git hub", "guit hub"), True),
    Site("maps", "Google Maps", "google.com/maps", ("maps", "mapas", "google mapas"), True),
    Site("gmail", "Gmail", "mail.google.com", ("email", "e-mail", "meu email", "gimeil")),
    Site("whatsapp", "WhatsApp", "web.whatsapp.com", ("zap", "whats", "uatsap", "zapzap")),
    Site("netflix", "Netflix", "netflix.com", ("netiflix",)),
    Site("twitch", "Twitch", "twitch.tv", ("tuitch",)),
    Site("instagram", "Instagram", "instagram.com", ("insta", "instagran")),
    Site("x", "X", "x.com", ("twitter", "tuiter")),
    Site("reddit", "Reddit", "reddit.com", ("redit", "rédit")),
    Site("chatgpt", "ChatGPT", "chatgpt.com", ("chat gpt", "chat gepete")),
    Site("claude", "Claude", "claude.ai", ("clode",)),
    Site("drive", "Google Drive", "drive.google.com", ("google drive", "meu drive")),
    Site("translate", "Google Tradutor", "translate.google.com", ("tradutor", "google tradutor")),
)

_CALL = r"^(?:(?:ei|ok|hey|oi)\s+)?(?:shiro\s+)?"
_POLITE = r"(?:\s+(?:por favor|pf|pfv|pra mim))?$"
_OPEN = re.compile(
    _CALL + r"(?:abr[ae]|abrir|entr[ae]|entrar|acess[ae]|acessar|vai|va)\s+"
    r"(?:(?:no|na|o|a|em|pro|pra)\s+)?(?:(?:site|pagina)\s+(?:do|da|de)\s+)?"
    r"(?P<site>[a-z0-9 ]+?)" + _POLITE
)
_SEARCH = re.compile(
    _CALL + r"(?:pesquis[ae]|pesquisar|procur[ae]|procurar|busc[ae]|buscar)\s+"
    r"(?:(?:por|sobre)\s+)?(?P<q>.+?)\s+(?:no|na|em)\s+(?:o\s+|a\s+)?"
    r"(?P<site>[a-z0-9 ]+?)" + _POLITE
)
_PLAY = re.compile(
    _CALL + r"(?:(?:pesquis[ae]|pesquisar|procur[ae]|procurar|busc[ae]|buscar)\s+"
    r"(?:(?:por|sobre)\s+)?(?P<q1>.+?)\s+e\s+)?"
    r"(?:pode\s+)?(?:toca|toque|tocar|coloca|coloque|colocar|bota|bote|botar|poe|ponha)\s+"
    r"(?:(?:a|o|um|uma)\s+(?:musica|video|clipe)\s+(?:do|da|de)?\s*)?"
    r"(?P<q2>.*?)\s*(?:no|na)\s+(?:o\s+)?(?P<site>[a-z0-9 ]+?)"
    r"(?:\s+(?:pra|para)\s+(?:tocar|eu ouvir|ouvir|mim))?" + _POLITE
)
_MATCH = 0.8


class SiteRules:
    """Regra do Tier 0 plugada no roteador quando o controle do PC está ligado."""

    def __init__(self, sites: tuple[Site, ...] = SITES) -> None:
        self._names: dict[str, Site] = {}
        self._sounds: dict[str, Site] = {}
        for site in sites:
            for name in (site.key, site.label, *site.aliases):
                self._names[normalize(name)] = site
                if len(sound := sound_key(name)) >= 3:
                    self._sounds[sound] = site

    def site(self, spoken: str) -> Site | None:
        name = normalize(spoken)
        if found := self._names.get(name):
            return found
        sound = sound_key(name)
        if len(sound) < 4:
            return None
        best = max(
            ((similarity(sound, known), site) for known, site in self._sounds.items()),
            key=lambda pair: pair[0],
            default=None,
        )
        return best[1] if best and best[0] >= _MATCH else None

    def __call__(self, text: str) -> Calls | None:
        command = normalize(text)
        if match := _PLAY.match(command):
            site = self.site(match["site"])
            spoken = (match["q1"] or match["q2"] or "").strip()
            if site is not None and site.key == "youtube" and spoken:
                query = _original_words(text, spoken).replace(",", "")
                return [("open_url", {"search": query, "on": "youtube", "play": True})]
        if match := _SEARCH.match(command):
            site = self.site(match["site"])
            if site is not None and site.search:
                query = _original_words(text, match["q"])
                return [("open_url", {"search": query, "on": site.key})]
            return None
        if match := _OPEN.match(command):
            site = self.site(match["site"])
            if site is not None:
                return [("open_url", {"url": site.url})]
        return None


def _original_words(text: str, plain: str) -> str:
    """A busca com os acentos e maiúsculas de como foi dita ("São Paulo", não "sao paulo")."""
    words = text.split()
    wanted = plain.split()
    for start in range(len(words) - len(wanted) + 1):
        window = words[start : start + len(wanted)]
        if [normalize(w) for w in window] == wanted:
            return " ".join(window).strip(" ,.;!?")
    return plain


def site_phrases(sites: tuple[Site, ...] = SITES) -> list[str]:
    """Frases como o Whisper escreve, para a correção de comandos (ADR-0021)."""
    return [f"Abra o {site.label}." for site in sites]


def site_words(sites: tuple[Site, ...] = SITES) -> list[str]:
    return [site.label for site in sites]


# --- programas e janelas ------------------------------------------------------

_ARTICLE = r"(?:(?:o|a|os|as)\s+)?"
_FOCUS = re.compile(
    _CALL + r"(?:(?:vai|volta|muda|troca|passa)\s+(?:pra|para|pro|pros|pras)\s+"
    r"|(?:abre|abra|mostra|mostre|traz|traga)\s+)"
    + _ARTICLE
    + r"janela\s+(?:do|da|de)\s+(?P<name>[a-z0-9 ]+?)"
    + _POLITE
)
_GO_TO = re.compile(
    _CALL
    + r"(?:vai|volta|muda|troca|passa)\s+(?:pra|para|pro|pros|pras)\s+"
    + _ARTICLE
    + r"(?P<name>[a-z0-9 ]+?)"
    + _POLITE
)
_START = re.compile(
    _CALL
    + r"(?:(?:no|na|pelo|pela)\s+[a-z0-9]+\s+)?"  # "na Steam, abra Half-Life"
    + r"(?:abre|abra|abrir|inicia|inicie|iniciar|executa|execute|roda|rode|liga|ligue|joga)\s+"
    + _ARTICLE
    + r"(?:programa\s+|aplicativo\s+|app\s+|jogo\s+)?(?P<name>[a-z0-9 ]+?)"
    + _POLITE
)

type NameMatcher = Callable[[str], str | None]


class ProgramRules:
    """ "abre a calculadora", "vai pra janela do Claude": sem passar pelo modelo.

    ``program`` e ``window`` acham o nome real (do menu Iniciar ou da janela) a
    partir do que foi dito; ``None`` quando não há nada parecido, e aí o pedido
    segue para o modelo.
    """

    def __init__(self, program: NameMatcher, window: NameMatcher) -> None:
        self._program = program
        self._window = window

    def __call__(self, text: str) -> Calls | None:
        command = normalize(text)
        focus = _FOCUS.match(command) or _GO_TO.match(command)
        if focus is not None:
            name = focus["name"]
            if self._window(name) is not None or self._program(name) is not None:
                return [("switch_window", {"name": name})]
            return None
        if (start := _START.match(command)) and self._program(start["name"]) is not None:
            return [("open_program", {"name": start["name"]})]
        return None


# --- ditado -------------------------------------------------------------------

_DICTATE = re.compile(
    _CALL + r"(?:(?:liga|ligue|ativa|ative|inicia|inicie|comeca|comece|abre|abra|entra no|"
    r"vou|quero)\s+)?(?:(?:o|um)\s+)?(?:modo\s+)?(?:ditado|ditar)" + _POLITE
)


def dictation_rule(text: str) -> Calls | None:
    """ "modo ditado", "liga o ditado", "vou ditar": liga sem passar pelo modelo."""
    return [("start_dictation", {})] if _DICTATE.match(normalize(text)) else None


# --- ler a tela em voz alta ------------------------------------------------------

_READ = re.compile(
    _CALL + r"(?:(?:me\s+)?(?:le|leia|ler|lê)|continua(?:\s+a)?\s+ler|continue(?:\s+a)?\s+ler)"
    r"(?:\s+(?:pra|para)\s+mim)?"
    r"(?:\s+(?P<what>(?:a|o|essa|esse|esta|este|isso|isto)(?:\s+(?:proxima|seguinte))?"
    r"(?:\s+(?:pagina|texto|tela|livro|capitulo|trecho|paragrafo))?))?"
    r"(?:\s+(?:da|na)\s+tela)?(?:\s+(?:pra|para)\s+mim)?"
    r"(?:\s+(?:traduzid[oa]|em)\s+(?:(?:pra|para)\s+)?(?:o\s+)?(?P<lang>portugues|ingles|espanhol))?"
    + _POLITE
)
_NEXT_ONLY = re.compile(
    _CALL + r"(?:proxima|vira a|passa a|passa pra|vai pra)\s*(?:a\s+)?pagina" + _POLITE
)
_LANGS = {"portugues": "português", "ingles": "inglês", "espanhol": "espanhol"}


_READ_WHAT_IS = re.compile(
    _CALL + r"(?:(?:eu\s+)?quero\s+que\s+(?:voce\s+)?)?(?:me\s+)?(?:le|leia|ler|lê)\s+"
    r"(?:pra mim\s+)?(?:o\s+)?(?:que|oque)\s+(?:esta|ta|tem|aparece)\s+(?:escrito\s+)?"
    r"(?:na|no)\s+(?:a\s+)?(?:tela|pagina|chrome|navegador|livro|pdf)\b"
)
_TRANSLATE_PAGE = re.compile(
    _CALL + r"(?:traduz|traduza|traduzir)\s+(?:pra mim\s+)?(?:e\s+(?:le|leia)\s+)?"
    r"(?:a|o|essa|esse|esta|este)\s+(?:pagina|tela|texto|livro|trecho|capitulo)\b"
)


def _target_language(command: str) -> str:
    for spoken, language in _LANGS.items():
        if re.search(rf"\b{spoken}\b", command):
            return language
    return "português"


_READ_AGAIN = re.compile(
    _CALL + r"(?:(?:volta|volte)\s+e\s+)?(?:(?:le|leia|ler|lê)\s+(?:de novo|novamente|outra vez)"
    r"|repete|repita|repetir)(?:\s+(?:a|o|essa|esse|isso)?\s*(?:ultima|mesma)?\s*"
    r"(?:pagina|trecho|parte|texto)?)?(?:\s+(?:de novo|pra mim))?" + _POLITE
)
_READ_BACK = re.compile(
    _CALL + r"(?:(?:volta|volte|retorna|retorne)\s+(?:uma|a|para a|pra)\s+pagina(?:\s+anterior)?"
    r"(?:\s+e\s+(?:le|leia|ler))?|(?:le|leia|ler|lê)\s+a\s+pagina\s+anterior|pagina anterior)"
    + _POLITE
)


_CONTINUE = re.compile(
    _CALL + r"(?:(?:pode\s+)?(?:continua|continue|continuar|segue|siga|prossiga|prossegue)"
    r"(?:\s+(?:a\s+)?(?:lendo|ler|leitura))?"
    r"|(?:(?:le|leia|ler|lê)\s+(?:o\s+)?)?proximo(?:\s+paragrafo)?)" + _POLITE
)
_PARAGRAPH_BACK = re.compile(
    _CALL + r"(?:(?:volta|volte)\s+(?:um|o|uma)\s+paragrafo|(?:(?:le|leia|ler|lê)\s+(?:o\s+)?)?"
    r"paragrafo\s+anterior)" + _POLITE
)
_READ_VERB = re.compile(r"\b(?:le|leia|ler|lendo|lê)\b")


def _reading_extras(command: str, args: dict[str, object]) -> dict[str, object]:
    """Modo (parágrafo/página) e tradução ditos junto do pedido de leitura."""
    if re.search(r"\bparagrafo", command):
        args["unit"] = "paragrafo"
    elif re.search(r"\bpagina (?:inteira|toda)\b|\btoda a pagina\b", command):
        args["unit"] = "pagina"
    if re.search(r"\btraduz", command) or re.search(
        r"\bem (?:portugues|ingles|espanhol)\b", command
    ):
        args.setdefault("translate_to", _target_language(command))
    return args


def reading_rule(text: str) -> Calls | None:
    """ "lê essa página pra mim", "lê a próxima página", "próxima página": sem o modelo."""
    command = normalize(text)
    if _CONTINUE.match(command):
        args: dict[str, object] = {"advance": True}
        if "paragrafo" in command:
            args["unit"] = "paragrafo"
        return [("read_aloud", args)]
    if _PARAGRAPH_BACK.match(command):
        return [("read_aloud", {"back": True, "unit": "paragrafo"})]
    if "paragrafo" in command and _READ_VERB.search(command):
        # "lê parágrafo por parágrafo", "lê um parágrafo por vez traduzido"
        return [("read_aloud", _reading_extras(command, {}))]
    if _READ_AGAIN.match(command):
        return [("read_aloud", {"again": True})]
    if _READ_BACK.match(command):
        return [("read_aloud", {"previous_page": True})]
    translating = re.search(r"\btraduz", command) is not None
    if _READ_WHAT_IS.match(command) or _TRANSLATE_PAGE.match(command):
        args: dict[str, object] = {}
        if translating:
            args["translate_to"] = _target_language(command)
        if re.search(r"\b(?:proxima|seguinte)\b", command):
            args["next_page"] = True
        return [("read_aloud", args)]
    if _NEXT_ONLY.match(command):
        return [("read_aloud", {"next_page": True})]
    match = _READ.match(command)
    if match is None:
        return None
    what = match["what"] or ""
    if not what and "continu" not in command:
        return None  # "lê" sozinho é vago demais: fica para o modelo
    args = {}
    if "continu" in command:
        return [("read_aloud", {"advance": True})]
    if "proxima" in what or "seguinte" in what:
        args["next_page"] = True
    if match["lang"]:
        args["translate_to"] = _LANGS[match["lang"]]
    return [("read_aloud", args)]
