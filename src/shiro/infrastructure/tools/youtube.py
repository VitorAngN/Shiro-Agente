"""Primeiro vídeo de uma busca no YouTube, para "toca X no YouTube" (ADR-0024).

Lê a página de resultados (a mesma que o navegador abriria) e pega o primeiro
``videoId``. Sem chave de API. Se o YouTube mudar a página, devolve ``None`` e
a SHIRO só abre a busca.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

_VIDEO = re.compile(r'"videoRenderer":\{"videoId":"([\w-]{11})"')
_ANY_VIDEO = re.compile(r'"videoId":"([\w-]{11})"')


def first_video_id(page: str) -> str | None:
    match = _VIDEO.search(page) or _ANY_VIDEO.search(page)
    return match.group(1) if match else None


class YouTubeFinder:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def first_video(self, query: str) -> str | None:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        try:
            response = await self._http.get(
                url,
                headers={"Accept-Language": "pt-BR,pt;q=0.9", "User-Agent": "Mozilla/5.0"},
                timeout=8.0,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        video = first_video_id(response.text)
        return f"https://www.youtube.com/watch?v={video}" if video else None
