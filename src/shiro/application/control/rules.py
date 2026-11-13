"""Tier 0 dos sites: "abre o YouTube", "pesquisa hollow knight no YouTube" (ADR-0024).

Sem passar pelo modelo: o pedido vira ``open_url`` na hora. Os nomes em
inglês são comparados pela pronúncia (``sound_key``), então "iutubi" e
"guitrub" também valem. Pedidos que não batem ficam para o modelo.
"""

from __future__ import annotations

import re
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
