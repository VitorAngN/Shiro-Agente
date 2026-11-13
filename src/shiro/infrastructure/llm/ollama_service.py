"""Garante que o Ollama está rodando antes de a SHIRO precisar dele.

No Windows o Ollama costuma iniciar com o sistema, mas nem sempre: depois de uma
atualização, ou se o usuário fechou o ícone da bandeja. Aqui o motor confere e,
se for preciso, sobe o ``ollama serve`` escondido.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)

_DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


class OllamaService:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        launch: Callable[[], bool] | None = None,
        wait_s: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._launch = launch or _launch_serve
        self._wait_s = wait_s

    async def running(self) -> bool:
        client = self._client or httpx.AsyncClient(timeout=2.0)
        try:
            response = await client.get(f"{self._base_url}/api/version")
            return response.status_code == 200
        except httpx.HTTPError:
            return False
        finally:
            if self._client is None:
                await client.aclose()

    async def ensure(self) -> str:
        """Sobe o Ollama se precisar; devolve uma linha para o usuário."""
        if await self.running():
            return "Ollama já estava rodando"
        if not self._launch():
            return "Ollama não encontrado: instale em ollama.com (sem ele, só a nuvem responde)"
        steps = max(1, int(self._wait_s / 0.5))
        for _ in range(steps):
            await asyncio.sleep(0.5)
            if await self.running():
                return "Ollama ligado"
        return "Ollama não respondeu a tempo (sem ele, só a nuvem responde)"


def _launch_serve() -> bool:
    exe = shutil.which("ollama")
    if exe is None:
        return False
    flags = _DETACHED if sys.platform == "win32" else 0
    subprocess.Popen(  # noqa: S603 - executável do próprio Ollama, sem shell
        [exe, "serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )
    log.info("ollama serve iniciado")
    return True
