"""Downloads com hash conferido."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from shiro.infrastructure.voice import models


async def test_download_checks_known_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"modelo de teste" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    seen: list[int] = []
    sha = await models.download(
        client, "https://x/a.onnx", tmp_path / "a.onnx", lambda _, done, __: seen.append(done)
    )
    assert (tmp_path / "a.onnx").read_bytes() == payload
    assert seen[-1] == len(payload)

    monkeypatch.setitem(models.KNOWN_SHA256, "b.onnx", "0" * 64)
    with pytest.raises(models.DownloadError, match="hash"):
        await models.download(client, "https://x/b.onnx", tmp_path / "b.onnx")
    assert not (tmp_path / "b.onnx").exists()
    assert not (tmp_path / "b.onnx.part").exists()

    monkeypatch.setitem(models.KNOWN_SHA256, "c.onnx", sha)
    files = models.kokoro_files(tmp_path, "int8")
    assert not files.present
    monkeypatch.setitem(models.KNOWN_SHA256, files.model.name, sha)
    monkeypatch.setitem(models.KNOWN_SHA256, files.voices.name, sha)
    await models.ensure_kokoro(client, tmp_path, "int8")
    assert models.kokoro_files(tmp_path, "int8").present

    missing = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    with pytest.raises(models.DownloadError, match="404"):
        await models.download(missing, "https://x/d.onnx", tmp_path / "d.onnx")
    await client.aclose()
    await missing.aclose()
