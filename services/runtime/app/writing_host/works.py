"""作品入口。壳只看见文档角色，不看见稿树路径。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.writing_host.errors import Busy, Conflict, ResumeIncompatible
from app.writing_host.schema import EVENT_KEEP_TURNS, SCHEMA_VERSIONS

_SKIP_PREFIXES = (
    ".agent/checkpoints/",
    ".agent/events/",
    ".agent/snapshots/",
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
    root = Path(work_root)
    objects = root / ".agent" / "snapshots" / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(_SKIP_PREFIXES) or rel == ".agent/host.json":
            continue
        data = path.read_bytes()
        digest = _sha(data)
        target = objects / digest
        if not target.is_file():
            target.write_bytes(data)
        files.append({"path": rel, "sha256": digest})
    manifest = {
        "schema_version": 1,
        "turn_id": turn_id,
        "created_at": _now(),
        "files": files,
    }
    dest = root / ".agent" / "snapshots" / "turns" / f"{turn_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    retain_recent_turns(root)


def list_turn_history(work_root: Path) -> list[TurnRecord]:
    directory = Path(work_root) / ".agent" / "snapshots" / "turns"
    if not directory.is_dir():
        return []
    rows: list[TurnRecord] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.append(TurnRecord(turn_id=str(data.get("turn_id") or path.stem), created_at=str(data.get("created_at") or "")))
    return rows


def revert_turn(work_root: Path, turn_id: str) -> None:
    root = Path(work_root)
    history = list_turn_history(root)
    ids = [row.turn_id for row in history]
    if turn_id not in ids:
        raise FileNotFoundError(turn_id)
    keep = ids[: ids.index(turn_id)]
    drop = ids[ids.index(turn_id) :]
    manifest_path = root / ".agent" / "snapshots" / "turns" / f"{turn_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wanted = {item["path"]: item["sha256"] for item in manifest.get("files") or []}
    objects = root / ".agent" / "snapshots" / "objects"
    for rel, digest in wanted.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((objects / digest).read_bytes())
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(_SKIP_PREFIXES) or rel in wanted:
            continue
        if rel.startswith(".agent/") and not rel.startswith(".agent/work/"):
            continue
        path.unlink(missing_ok=True)
    for dropped in drop:
        _unlink(root / ".agent" / "snapshots" / "turns" / f"{dropped}.json")
        _unlink(root / ".agent" / "checkpoints" / f"{dropped}.json")
        _unlink(root / ".agent" / "events" / f"{dropped}.jsonl")
    del keep


def export_work(work_root: Path, dest: Path) -> None:
    root = Path(work_root)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    from app.writing.version import core_version

    export_meta = {
        "core_version": core_version(),
        "schema_versions": SCHEMA_VERSIONS,
        "exported_at": _now(),
    }
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("export.json", json.dumps(export_meta, ensure_ascii=False))
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


def import_work(src: Path, work_root: Path) -> WorkView:
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as archive:
        meta_raw = archive.read("export.json")
        meta = json.loads(meta_raw)
        incoming = meta.get("schema_versions") or {}
        for name, version in incoming.items():
            current = int(SCHEMA_VERSIONS.get(name) or 0)
            if int(version) > current:
                raise ResumeIncompatible(detail=f"{name} schema {version}")
        archive.extractall(root)
    exported = root / "export.json"
    if exported.is_file():
        exported.unlink()
    return work_view(root)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def retain_recent_turns(work_root: Path) -> None:
    """快照与事件只留最近 32 回合，丢掉的回合连同断点一起删。"""
    root = Path(work_root)
    ranked: dict[str, int] = {}
    turns_dir = root / ".agent" / "snapshots" / "turns"
    if turns_dir.is_dir():
        for path in turns_dir.glob("*.json"):
            turn_id, stamp = _turn_stamp(path, "turn_id")
            ranked[turn_id] = max(ranked.get(turn_id, 0), stamp)
    events_dir = root / ".agent" / "events"
    if events_dir.is_dir():
        for path in events_dir.glob("*.jsonl"):
            turn_id, stamp = _turn_stamp(path, "turn_id")
            ranked[turn_id] = max(ranked.get(turn_id, 0), stamp)
    if len(ranked) <= EVENT_KEEP_TURNS:
        return
    ordered = sorted(ranked, key=lambda turn_id: (ranked[turn_id], turn_id))
    for turn_id in ordered[: len(ordered) - EVENT_KEEP_TURNS]:
        _unlink(turns_dir / f"{turn_id}.json")
        _unlink(events_dir / f"{turn_id}.jsonl")
        _unlink(root / ".agent" / "checkpoints" / f"{turn_id}.json")
    _gc_snapshot_objects(root)


def _turn_stamp(path: Path, id_key: str) -> tuple[str, int]:
    turn_id = path.stem
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            turn_id = str(data.get(id_key) or path.stem)
    return turn_id, path.stat().st_mtime_ns


def _gc_snapshot_objects(root: Path) -> None:
    objects = root / ".agent" / "snapshots" / "objects"
    turns = root / ".agent" / "snapshots" / "turns"
    if not objects.is_dir():
        return
    used: set[str] = set()
    if turns.is_dir():
        for path in turns.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            if not isinstance(data, dict):
                return
            for item in data.get("files") or []:
                if isinstance(item, dict) and item.get("sha256"):
                    used.add(str(item["sha256"]))
    for path in objects.iterdir():
        if path.is_file() and path.name not in used:
            path.unlink(missing_ok=True)
