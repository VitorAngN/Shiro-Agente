"""Arquivos só nas pastas permitidas, lixeira com restauração e organizar com plano."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from shiro.domain.models import RiskLevel
from shiro.domain.ports import ToolContext
from shiro.infrastructure.tools.files import (
    AllowedFolders,
    FileAccessError,
    FindFilesTool,
    ListFilesTool,
    MoveFileTool,
    OrganizeArgs,
    OrganizeFolderTool,
    RenameFileTool,
    RestoreFileTool,
    Trash,
    TrashFileTool,
    organize_plan,
)
from tests.fakes.agent import SAO_PAULO
from tests.fakes.clock import MovableClock

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=SAO_PAULO)
CTX = ToolContext(trace_id="t", now=NOW)


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for index, name in enumerate(
        ["boleto-luz.pdf", "foto praia.JPG", "setup.exe", "notas.txt", "musica.mp3", "x.crdownload"]
    ):
        path = folder / name
        path.write_text(name)
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    (folder / ".escondido").write_text("x")
    return folder


async def test_list_and_find_only_inside_allowed_folders(downloads: Path, tmp_path: Path) -> None:
    folders = AllowedFolders([downloads])
    listed = await ListFilesTool(folders).run(ListFilesTool.spec.args_model(), CTX)
    assert listed.content.startswith("6 em Downloads, mais recentes: x.crdownload; musica.mp3")
    assert ".escondido" not in listed.content
    only_pdf = await ListFilesTool(folders).run(
        ListFilesTool.spec.args_model(folder="downloads", contains="boleto"), CTX
    )
    assert "boleto-luz.pdf" in only_pdf.content and "setup" not in only_pdf.content
    found = await FindFilesTool(folders).run(FindFilesTool.spec.args_model(name="praia"), CTX)
    assert "foto praia.JPG (em Downloads)" in found.content

    other = await ListFilesTool(folders).run(
        ListFilesTool.spec.args_model(folder="documentos"), CTX
    )
    assert not other.ok and "não está liberada" in other.content
    with pytest.raises(FileAccessError):
        folders.check(downloads / ".." / "fora.txt")
    with pytest.raises(FileAccessError, match="nenhuma pasta"):
        AllowedFolders([]).root()
    assert ListFilesTool.spec.output_trusted is False  # nomes de arquivo são conteúdo externo
    assert ListFilesTool.spec.local_only is True


async def test_move_rename_and_refuse_escape(downloads: Path) -> None:
    folders = AllowedFolders([downloads])
    moved = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="boleto", to="Contas"), CTX
    )
    assert moved.ok and (downloads / "Contas" / "boleto-luz.pdf").is_file()
    escape = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="notas", to="../../fora"), CTX
    )
    assert not escape.ok and "fora das pastas" in escape.content
    renamed = await RenameFileTool(folders).run(
        RenameFileTool.spec.args_model(name="notas.txt", new_name="../anotações"), CTX
    )
    assert renamed.ok and (downloads / "anotações.txt").is_file()  # a barra é ignorada
    clash = await RenameFileTool(folders).run(
        RenameFileTool.spec.args_model(name="musica", new_name="setup.exe"), CTX
    )
    assert not clash.ok and "Já existe" in clash.content
    missing = await MoveFileTool(folders).run(
        MoveFileTool.spec.args_model(name="nada", to="x"), CTX
    )
    assert not missing.ok


async def test_ambiguous_names_ask_which(downloads: Path) -> None:
    (downloads / "boleto-agua.pdf").write_text("x")
    folders = AllowedFolders([downloads])
    answer = await TrashFileTool(
        folders, Trash(downloads.parent / "lixo", MovableClock(NOW)), 7
    ).run(TrashFileTool.spec.args_model(name="boleto"), CTX)
    assert not answer.ok and "Qual deles?" in answer.content


async def test_trash_restore_and_purge(downloads: Path, tmp_path: Path) -> None:
    clock = MovableClock(NOW)
    trash = Trash(tmp_path / "lixeira", clock)
    folders = AllowedFolders([downloads])
    gone = await TrashFileTool(folders, trash, 7).run(
        TrashFileTool.spec.args_model(name="setup.exe"), CTX
    )
    assert gone.ok and "restaurar por 7 dias" in gone.content
    assert not (downloads / "setup.exe").exists()
    assert [i.name for i in trash.items()] == ["setup.exe"]

    back = await RestoreFileTool(folders, trash).run(
        RestoreFileTool.spec.args_model(name="setup"), CTX
    )
    assert back.ok and (downloads / "setup.exe").read_text() == "setup.exe"
    assert trash.items() == []
    assert not (
        await RestoreFileTool(folders, trash).run(
            RestoreFileTool.spec.args_model(name="setup"), CTX
        )
    ).ok

    await TrashFileTool(folders, trash, 7).run(TrashFileTool.spec.args_model(name="notas"), CTX)
    assert trash.purge(timedelta(days=7)) == 0
    clock.current = NOW + timedelta(days=8)
    assert trash.purge(timedelta(days=7)) == 1
    assert trash.items() == []


async def test_organize_shows_the_plan_before_moving(downloads: Path) -> None:
    folders = AllowedFolders([downloads])
    tool = OrganizeFolderTool(folders)
    assert tool.spec.confirm and tool.spec.risk is RiskLevel.R2
    plan_text = tool.describe(OrganizeArgs(folder="downloads"))
    assert plan_text.startswith("organizar Downloads: mover 5 arquivos (")
    assert "1 em Imagens" in plan_text and "1 em Instaladores" in plan_text
    assert (downloads / "setup.exe").exists()  # descrever não mexe em nada

    done = await tool.run(OrganizeArgs(folder="downloads"), CTX)
    assert done.ok
    assert (downloads / "Imagens" / "foto praia.JPG").is_file()
    assert (downloads / "Documentos" / "boleto-luz.pdf").is_file()
    assert (downloads / "x.crdownload").is_file()  # download em andamento fica onde está
    assert (await tool.run(OrganizeArgs(folder="downloads"), CTX)).content.endswith(
        "já está organizada."
    )
    assert organize_plan([Path("a.xyz")]) == {"Outros": [Path("a.xyz")]}


@pytest.mark.skipif(sys.platform == "win32", reason="permissões de link simbólico no Windows")
def test_symlinks_out_of_the_folder_are_ignored(downloads: Path, tmp_path: Path) -> None:
    outside = tmp_path / "segredo.txt"
    outside.write_text("x")
    (downloads / "atalho.txt").symlink_to(outside)
    folders = AllowedFolders([downloads])
    assert "atalho.txt" not in [p.name for p in folders.files(downloads)]
    with pytest.raises(FileAccessError):
        folders.check(downloads / "atalho.txt")
