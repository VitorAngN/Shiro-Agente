"""Arquivos nas pastas permitidas (RF-24, RF-25, ADR-0018).

* Só enxerga as pastas de ``policy.allowed_folders`` (padrão: Downloads). Todo
  caminho é resolvido e conferido: ``..`` ou atalho que saia da pasta é recusado.
* Nomes de arquivo são conteúdo externo (``output_trusted=False``): um arquivo
  chamado "ignore as instruções.txt" não vira ordem.
* "Apagar" nunca apaga: move para a lixeira da SHIRO, de onde dá para restaurar
  até ``retention.trash_days`` dias depois.
* "Organizar" mostra o plano na própria confirmação antes de mexer em qualquer coisa.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from shiro.domain.models import RiskLevel, ToolResult
from shiro.domain.ports import Clock, Tool, ToolContext, ToolSpec
from shiro.domain.text import normalize
from shiro.infrastructure.tools._base import Args, expect

_SKIP_SUFFIXES = {".crdownload", ".part", ".tmp", ".partial", ".download"}
CATEGORIES: dict[str, tuple[str, ...]] = {
    "Imagens": ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "heic", "tif", "tiff"),
    "Documentos": (
        "pdf", "doc", "docx", "odt", "txt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp",
        "csv", "md", "epub",
    ),
    "Compactados": ("zip", "rar", "7z", "tar", "gz", "bz2", "xz"),
    "Instaladores": ("exe", "msi", "msix", "appx"),
    "Videos": ("mp4", "mkv", "avi", "mov", "webm", "wmv"),
    "Audio": ("mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"),
}  # fmt: skip
_BY_EXTENSION = {ext: folder for folder, exts in CATEGORIES.items() for ext in exts}
_MAX_LISTED = 15
_MAX_SCAN = 2000


class FileAccessError(ValueError):
    pass


class AllowedFolders:
    """As pastas liberadas, com apelidos falados ("downloads", "documentos")."""

    def __init__(self, folders: Sequence[str | Path]) -> None:
        self.roots: dict[str, Path] = {}
        for folder in folders:
            path = Path(folder).expanduser().resolve()
            self.roots[normalize(path.name)] = path

    def __bool__(self) -> bool:
        return bool(self.roots)

    def root(self, alias: str = "") -> Path:
        if not self.roots:
            msg = "nenhuma pasta liberada: configure policy.allowed_folders no shiro.toml"
            raise FileAccessError(msg)
        if not alias.strip():
            return next(iter(self.roots.values()))
        key = normalize(alias).removeprefix("pasta ").removeprefix("meus ").removeprefix("minha ")
        for name, path in self.roots.items():
            if key in (name, name.rstrip("s")) or name.startswith(key):
                return path
        known = ", ".join(p.name for p in self.roots.values())
        msg = f'a pasta "{alias}" não está liberada (liberadas: {known})'
        raise FileAccessError(msg)

    def check(self, path: Path) -> Path:
        """Caminho real, garantidamente dentro de uma pasta liberada."""
        real = path.resolve()
        if not any(real == root or real.is_relative_to(root) for root in self.roots.values()):
            msg = "esse caminho fica fora das pastas liberadas"
            raise FileAccessError(msg)
        return real

    def files(self, root: Path, *, recursive: bool = False) -> list[Path]:
        pattern = root.rglob("*") if recursive else root.glob("*")
        found: list[Path] = []
        for path in pattern:
            if len(found) >= _MAX_SCAN:
                break
            if path.is_file() and not path.name.startswith(".") and not path.is_symlink():
                found.append(path)
        return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

    def find(self, name: str) -> list[Path]:
        wanted = normalize(name)
        matches: list[Path] = []
        for root in self.roots.values():
            for path in self.files(root, recursive=True):
                if wanted == normalize(path.name) or wanted in normalize(path.name):
                    matches.append(path)
        exact = [p for p in matches if normalize(p.name) == wanted or normalize(p.stem) == wanted]
        return exact or matches


def unique_target(folder: Path, name: str) -> Path:
    """``folder/name``, ou ``nome (2).ext`` se já existir."""
    target = folder / name
    counter = 2
    while target.exists():
        target = folder / f"{Path(name).stem} ({counter}){Path(name).suffix}"
        counter += 1
    return target


@dataclass(frozen=True)
class TrashItem:
    folder: Path
    name: str
    original: Path
    deleted_at: datetime


class Trash:
    """Lixeira da SHIRO: ``<dados>/trash/<id>/<arquivo>`` + ``meta.json``."""

    def __init__(self, folder: Path, clock: Clock) -> None:
        self._folder = folder
        self._clock = clock

    def put(self, path: Path) -> TrashItem:
        slot = self._folder / uuid.uuid4().hex
        slot.mkdir(parents=True)
        now = self._clock.now()
        shutil.move(str(path), str(slot / path.name))
        meta = {"original": str(path), "deleted_at": now.isoformat()}
        (slot / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return TrashItem(slot, path.name, path, now)

    def items(self) -> list[TrashItem]:
        if not self._folder.is_dir():
            return []
        found: list[TrashItem] = []
        for slot in self._folder.iterdir():
            meta_file = slot / "meta.json"
            if not meta_file.is_file():
                continue
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            original = Path(meta["original"])
            found.append(
                TrashItem(slot, original.name, original, datetime.fromisoformat(meta["deleted_at"]))
            )
        return sorted(found, key=lambda item: item.deleted_at, reverse=True)

    def restore(self, item: TrashItem) -> Path:
        item.original.parent.mkdir(parents=True, exist_ok=True)
        target = unique_target(item.original.parent, item.name)
        shutil.move(str(item.folder / item.name), str(target))
        shutil.rmtree(item.folder)
        return target

    def purge(self, older_than: timedelta) -> int:
        """Apaga de vez o que está na lixeira há mais tempo que ``older_than``."""
        limit = self._clock.now() - older_than
        removed = 0
        for item in self.items():
            if item.deleted_at < limit:
                shutil.rmtree(item.folder)
                removed += 1
        return removed


def organize_plan(files: Sequence[Path]) -> dict[str, list[Path]]:
    plan: dict[str, list[Path]] = {}
    for path in files:
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        category = _BY_EXTENSION.get(path.suffix.lower().lstrip("."), "Outros")
        plan.setdefault(category, []).append(path)
    return plan


def describe_plan(plan: dict[str, list[Path]]) -> str:
    total = sum(len(v) for v in plan.values())
    parts = ", ".join(f"{len(v)} em {k}" for k, v in sorted(plan.items(), key=lambda i: -len(i[1])))
    return f"{total} arquivo{'s' if total != 1 else ''} ({parts})" if total else "nada a mover"


# ---------------------------------------------------------------------- argumentos


class FolderArgs(Args):
    folder: str = Field(default="", description="Pasta liberada ('downloads'); vazio = a primeira")
    contains: str = Field(default="", description="Parte do nome para filtrar, opcional")


class NameArgs(Args):
    name: str = Field(min_length=1, description="Nome ou parte do nome do arquivo")


class MoveArgs(NameArgs):
    to: str = Field(min_length=1, description="Subpasta de destino dentro da pasta liberada")


class RenameArgs(NameArgs):
    new_name: str = Field(min_length=1, max_length=200, description="Novo nome do arquivo")


class OrganizeArgs(Args):
    folder: str = Field(default="", description="Pasta liberada a organizar ('downloads')")


# ---------------------------------------------------------------------- ferramentas


class _FileTool:
    spec: ToolSpec

    def __init__(self, folders: AllowedFolders) -> None:
        self._folders = folders

    def _one(self, name: str) -> Path | ToolResult:
        matches = self._folders.find(name)
        if not matches:
            return ToolResult.failure(
                f'Não achei nenhum arquivo com "{name}" nas pastas liberadas.'
            )
        if len(matches) > 1:
            listed = "; ".join(p.name for p in matches[:5])
            return ToolResult.failure(f"Achei {len(matches)}: {listed}. Qual deles?")
        return self._folders.check(matches[0])


def _spec(
    name: str,
    description: str,
    args: type[BaseModel],
    risk: RiskLevel,
    *,
    confirm: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args_model=args,
        risk=risk,
        timeout_s=30.0,
        output_trusted=False,
        local_only=True,
        confirm=confirm,
        group="files",
    )


class ListFilesTool(_FileTool):
    spec = _spec(
        "list_files",
        "Lista os arquivos mais recentes de uma pasta liberada.",
        FolderArgs,
        RiskLevel.R0,
    )

    def describe(self, args: BaseModel) -> str:
        return "listar arquivos"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        a = expect(args, FolderArgs)
        try:
            root = self._folders.root(a.folder)
        except FileAccessError as exc:
            return ToolResult.failure(f"{exc}.")
        files = self._folders.files(root)
        if a.contains:
            files = [p for p in files if normalize(a.contains) in normalize(p.name)]
        if not files:
            return ToolResult.success(f"Nenhum arquivo em {root.name}.")
        shown = "; ".join(p.name for p in files[:_MAX_LISTED])
        more = f" (e mais {len(files) - _MAX_LISTED})" if len(files) > _MAX_LISTED else ""
        return ToolResult.success(f"{len(files)} em {root.name}, mais recentes: {shown}{more}.")


class FindFilesTool(_FileTool):
    spec = _spec(
        "find_files", "Procura arquivos pelo nome nas pastas liberadas.", NameArgs, RiskLevel.R0
    )

    def describe(self, args: BaseModel) -> str:
        return f"procurar {expect(args, NameArgs).name}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        matches = self._folders.find(expect(args, NameArgs).name)
        if not matches:
            return ToolResult.success("Não achei nada com esse nome.")
        shown = "; ".join(f"{p.name} (em {p.parent.name})" for p in matches[:_MAX_LISTED])
        return ToolResult.success(f"Achei {len(matches)}: {shown}.")


class MoveFileTool(_FileTool):
    spec = _spec(
        "move_file",
        "Move um arquivo para uma subpasta dentro da mesma pasta liberada.",
        MoveArgs,
        RiskLevel.R2,
    )

    def describe(self, args: BaseModel) -> str:
        a = expect(args, MoveArgs)
        return f"mover {a.name} para {a.to}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        a = expect(args, MoveArgs)
        found = self._one(a.name)
        if isinstance(found, ToolResult):
            return found
        root = next(r for r in self._folders.roots.values() if found.is_relative_to(r))
        try:
            destination = self._folders.check(root / a.to)
        except FileAccessError as exc:
            return ToolResult.failure(f"{exc}.")
        destination.mkdir(parents=True, exist_ok=True)
        target = unique_target(destination, found.name)
        shutil.move(str(found), str(target))
        return ToolResult.success(f"Movido: {found.name} para {destination.name}.")


class RenameFileTool(_FileTool):
    spec = _spec("rename_file", "Renomeia um arquivo.", RenameArgs, RiskLevel.R2)

    def describe(self, args: BaseModel) -> str:
        a = expect(args, RenameArgs)
        return f"renomear {a.name} para {a.new_name}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        a = expect(args, RenameArgs)
        found = self._one(a.name)
        if isinstance(found, ToolResult):
            return found
        new_name = Path(a.new_name).name  # sem barras: nunca troca de pasta
        if not Path(new_name).suffix:
            new_name += found.suffix
        target = found.with_name(new_name)
        if target.exists():
            return ToolResult.failure(f"Já existe um arquivo chamado {new_name}.")
        found.rename(target)
        return ToolResult.success(f"Renomeado: {found.name} para {new_name}.")


class TrashFileTool(_FileTool):
    spec = _spec(
        "trash_file",
        "Manda um arquivo para a lixeira da SHIRO (dá para restaurar). Use para 'apagar'.",
        NameArgs,
        RiskLevel.R2,
    )

    def __init__(self, folders: AllowedFolders, trash: Trash, keep_days: int) -> None:
        super().__init__(folders)
        self._trash = trash
        self._keep_days = keep_days

    def describe(self, args: BaseModel) -> str:
        return f"mandar {expect(args, NameArgs).name} para a lixeira"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        found = self._one(expect(args, NameArgs).name)
        if isinstance(found, ToolResult):
            return found
        self._trash.put(found)
        return ToolResult.success(
            f"{found.name} foi para a lixeira; dá para restaurar por {self._keep_days} dias."
        )


class RestoreFileTool(_FileTool):
    spec = _spec("restore_file", "Restaura um arquivo da lixeira da SHIRO.", NameArgs, RiskLevel.R1)

    def __init__(self, folders: AllowedFolders, trash: Trash) -> None:
        super().__init__(folders)
        self._trash = trash

    def describe(self, args: BaseModel) -> str:
        return f"restaurar {expect(args, NameArgs).name}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        wanted = normalize(expect(args, NameArgs).name)
        matches = [i for i in self._trash.items() if wanted in normalize(i.name)]
        if not matches:
            return ToolResult.failure("Não achei esse arquivo na lixeira.")
        restored = self._trash.restore(matches[0])
        return ToolResult.success(f"Restaurado: {restored.name}, em {restored.parent.name}.")


class OrganizeFolderTool(_FileTool):
    spec = _spec(
        "organize_folder",
        "Organiza uma pasta liberada em subpastas por tipo (Imagens, Documentos...).",
        OrganizeArgs,
        RiskLevel.R2,
        confirm=True,
    )

    def describe(self, args: BaseModel) -> str:
        """A confirmação já mostra o plano: é o "dry-run" antes de mexer."""
        try:
            root = self._folders.root(expect(args, OrganizeArgs).folder)
        except FileAccessError as exc:
            return f"organizar uma pasta ({exc})"
        plan = organize_plan(self._folders.files(root))
        return f"organizar {root.name}: mover {describe_plan(plan)}"

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        try:
            root = self._folders.root(expect(args, OrganizeArgs).folder)
        except FileAccessError as exc:
            return ToolResult.failure(f"{exc}.")
        plan = organize_plan(self._folders.files(root))
        moved: Counter[str] = Counter()
        for category, paths in plan.items():
            destination = root / category
            destination.mkdir(exist_ok=True)
            for path in paths:
                shutil.move(str(path), str(unique_target(destination, path.name)))
                moved[category] += 1
        if not moved:
            return ToolResult.success(f"{root.name} já está organizada.")
        return ToolResult.success(f"Organizei {root.name}: {describe_plan(plan)}.")


def file_tools(folders: AllowedFolders, trash: Trash, keep_days: int) -> list[Tool]:
    return [
        ListFilesTool(folders),
        FindFilesTool(folders),
        MoveFileTool(folders),
        RenameFileTool(folders),
        TrashFileTool(folders, trash, keep_days),
        RestoreFileTool(folders, trash),
        OrganizeFolderTool(folders),
    ]
