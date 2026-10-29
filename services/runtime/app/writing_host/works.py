"""作品入口。壳只看见文档角色，不看见稿树路径。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.writing_host.errors import Busy, Conflict
from app.writing_host.schema import SCHEMA_VERSIONS
from app.writing_host.storage import (
    history,
    revert_turn as revert_locked,
    work_lock,
    write_snapshot,
)


@dataclass
class Document:
    doc_id: str
    role: str
    title: str
    visible_chars: int
    revision: str
    text: str = ""
    modified_at: str = ""


@dataclass
class WorkView:
    work_id: str
    title: str
    core_version: str
    documents: list[Document] = field(default_factory=list)


@dataclass
class TurnRecord:
    turn_id: str
    created_at: str
    seq: int = 0
    state: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _visible(text: str) -> int:
    return len("".join(text.split()))


def _catalog(work_root: Path) -> list[tuple[str, str, str, Path]]:
    """返回 ``(doc_id, role, title, path)``。路径只留在接头内。"""
    rows: list[tuple[str, str, str, Path]] = []
    outline = work_root / "outline.md"
    if outline.is_file():
        rows.append(("outline", "outline", "大纲", outline))
    manuscript = work_root / "drafts" / "manuscript.md"
    if manuscript.is_file():
        rows.append(("manuscript", "manuscript", "正文", manuscript))
    archive = work_root / "drafts" / "archive"
    if archive.is_dir():
        for path in sorted(archive.rglob("*")):
            if path.is_file():
                rel = path.relative_to(archive).as_posix()
                rows.append((f"archive:{rel}", "archive", rel, path))
    cards = work_root / "sources" / "cards"
    if cards.is_dir():
        for path in sorted(cards.rglob("*")):
            if path.is_file():
                rel = path.relative_to(cards).as_posix()
                rows.append((f"cards:{rel}", "cards", rel, path))
    notes = work_root / ".agent" / "work"
    if notes.is_dir():
        for name in ("author_notes.md", "editor_notes.md", "story_state.json"):
            path = notes / name
            if path.is_file():
                rows.append((f"notes:{name}", "notes", name, path))
    return rows


def _doc_from_path(doc_id: str, role: str, title: str, path: Path, *, with_text: bool) -> Document:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Document(
        doc_id=doc_id,
        role=role,
        title=title,
        visible_chars=_visible(text),
        revision=_sha(data)[:16],
        text=text if with_text else "",
        modified_at=modified,
    )


def work_view(work_root: Path) -> WorkView:
    root = Path(work_root)
    host = root / ".agent" / "host.json"
    work_id = ""
    if host.is_file():
        work_id = str(json.loads(host.read_text(encoding="utf-8")).get("work_id") or "")
    from app.writing.version import core_version

    title = ""
    outline = root / "outline.md"
    if outline.is_file():
        for line in outline.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                title = stripped[:80]
                break
    documents = [
        _doc_from_path(doc_id, role, label, path, with_text=False)
        for doc_id, role, label, path in _catalog(root)
    ]
    return WorkView(work_id=work_id, title=title or root.name, core_version=core_version(), documents=documents)


def read_document(work_root: Path, doc_id: str) -> Document:
    found = _find(work_root, doc_id)
    doc_id, role, title, path = found
    return _doc_from_path(doc_id, role, title, path, with_text=True)


def write_document(work_root: Path, doc_id: str, text: str, *, base_revision: str, busy: bool) -> Document:
    if busy:
        raise Busy()
    with work_lock(work_root):
        doc_id, role, title, path = _find(work_root, doc_id)
        current = _sha(path.read_bytes())[:16]
        if current != base_revision:
            raise Conflict()
        path.write_text(text, encoding="utf-8")
        return _doc_from_path(doc_id, role, title, path, with_text=True)


def _find(work_root: Path, doc_id: str) -> tuple[str, str, str, Path]:
    for row in _catalog(Path(work_root)):
        if row[0] == doc_id:
            return row
    raise FileNotFoundError(doc_id)


def snapshot_turn(work_root: Path, turn_id: str) -> None:
    write_snapshot(Path(work_root), turn_id)


def list_turn_history(work_root: Path) -> list[TurnRecord]:
    return [
        TurnRecord(
            turn_id=str(row["turn_id"]),
            created_at=str(row.get("created_at") or ""),
            seq=int(row.get("seq") or 0),
            state=str(row.get("state") or ""),
        )
        for row in history(Path(work_root))
    ]


def revert_turn(work_root: Path, turn_id: str) -> None:
    revert_locked(Path(work_root), turn_id)


def export_work(work_root: Path, dest: Path, *, mode: str = "manuscript", min_free_bytes: int | None = None) -> None:
    from app.writing_host.storage import ensure_space

    root = Path(work_root)
    dest = Path(dest)
    if mode not in {"manuscript", "full"}:
        raise ValueError(mode)
    ensure_space(root, min_free_bytes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    from app.writing.version import core_version

    export_meta = {
        "core_version": core_version(),
        "schema_versions": SCHEMA_VERSIONS,
        "exported_at": _now(),
        "mode": mode,
    }
    with work_lock(root):
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("export.json", json.dumps(export_meta, ensure_ascii=False))
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if rel == ".agent/lock":
                    continue
                if mode == "manuscript" and (rel.startswith(_MANUSCRIPT_SKIP) or rel in _MANUSCRIPT_SKIP):
                    continue
                archive.write(path, rel)


_MANUSCRIPT_SKIP = (
    ".agent/snapshots/",
    ".agent/events/",
    ".agent/checkpoints/",
    ".agent/evaluations/",
    ".agent/turns.json",
)


def import_work(src: Path, work_root: Path) -> WorkView:
    from app.writing_host.storage import import_work as impl

    return impl(Path(src), Path(work_root))
