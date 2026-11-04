"""Download dos modelos de voz com cada arquivo conferido."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from shiro.infrastructure.system.downloads import COMPLETE_MARK
from shiro.infrastructure.voice import models


async def test_whisper_download_verifies_every_file(tmp_path: Path) -> None:
    import hashlib

    files = {"config.json": b'{"a": 1}', "vocabulary.txt": b"oi\n", "model.bin": b"\x00" * 4096}

    def blob(content: bytes) -> str:
        header = f"blob {len(content)}\0".encode()
        return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()

    tree = [
        {"type": "file", "path": ".gitattributes", "size": 1, "oid": "x"},
        {"type": "file", "path": "config.json", "size": 8, "oid": blob(files["config.json"])},
        {"type": "file", "path": "vocabulary.txt", "size": 3, "oid": blob(files["vocabulary.txt"])},
        {
            "type": "file",
            "path": "model.bin",
            "size": 4096,
            "lfs": {"oid": hashlib.sha256(files["model.bin"]).hexdigest()},
        },
    ]
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if "/api/models/" in request.url.path:
            return httpx.Response(200, json=tree)
        return httpx.Response(200, content=files[request.url.path.rsplit("/", 1)[-1]])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    folder = await models.ensure_whisper(client, tmp_path, "small")

    assert folder.name == "Systran--faster-whisper-small"
    assert (folder / "model.bin").read_bytes() == files["model.bin"]
    assert not (folder / ".gitattributes").exists()
    assert models.whisper_ready(tmp_path, "small")
    count = len(requests)
    assert await models.ensure_whisper(client, tmp_path, "small") == folder
    assert len(requests) == count  # pronto: não consulta de novo

    files["vocabulary.txt"] = b"adulterado"
    with pytest.raises(models.DownloadError, match="hash"):
        await models.ensure_whisper(client, tmp_path / "outro", "base")
    assert models.whisper_repo("org/modelo") == "org/modelo"

    missing = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(models.DownloadError, match="404"):
        await models.ensure_whisper(missing, tmp_path / "x", "nada")
    empty = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[])))
    with pytest.raises(models.DownloadError, match="faster-whisper"):
        await models.ensure_whisper(empty, tmp_path / "y", "outra")
    for c in (client, missing, empty):
        await c.aclose()


def test_whisper_without_vocabulary_is_not_ready(tmp_path: Path) -> None:
    from shiro.infrastructure.voice.models import whisper_dir, whisper_ready

    folder = whisper_dir(tmp_path, "large-v3-turbo")
    assert folder.name == "mobiuslabsgmbh--faster-whisper-large-v3-turbo"
    folder.mkdir(parents=True)
    (folder / COMPLETE_MARK).write_text("x")
    assert not whisper_ready(tmp_path, "large-v3-turbo")  # falta o vocabulário
    (folder / "vocabulary.json").write_text("{}")
    assert whisper_ready(tmp_path, "large-v3-turbo")
