"""写作「这本书」：用户看见的稿件对象，不是目录树。

左侧只放正文、已确认、大纲。没有内容的一项不出现。
扔掉整本时清用户稿与 `.agent/work` 侧车；不动资料库、种子语料、会话。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.writing.manuscript import (
    confirmed_manuscript_rel,
    draft_manuscript_rel,
    legacy_draft_manuscript_rel,
)
from app.writing.occupy import ARCHIVE_DIR
from app.writing.outline_phase import clear_style_lock
from app.writing.text_metrics import visible_chars

_TEXT_CAP = 80_000


def _workspace(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def _is_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _clip(text: str, *, cap: int = _TEXT_CAP) -> str:
    body = (text or "").strip()
    if len(body) <= cap:
        return body
    return body[: cap - 1].rstrip() + "…"


def _first_heading(text: str) -> str:
    for line in (text or "").splitlines():
        raw = line.strip()
        if raw.startswith("#"):
            title = raw.lstrip("#").strip()
            if title:
                return title
    for line in (text or "").splitlines():
        raw = line.strip()
        if raw:
            return raw[:40]
    return ""


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _public_rel(root: Path, path: Path) -> str:
    rel = _rel(root, path)
    if rel == ".agent" or rel.startswith(".agent/"):
        return ""
    return rel


def _part(
    *,
    key: str,
    label: str,
    text: str,
    kind: str = "",
    path: str = "",
) -> dict[str, Any]:
    body = _clip(text)
    out: dict[str, Any] = {
        "key": key,
        "label": label,
        "kind": kind,
        "chars": visible_chars(body),
        "text": body,
    }
    if path:
        out["path"] = path
    return out


def load_writing_book(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """组装这本书的可见部件（不含路径）。"""
    root = _workspace(workspace_root)
    outline_path = root / "outline.md"
    outline = _read_text(outline_path)
    ms_rel = draft_manuscript_rel()
    manuscript = _read_text(root / ms_rel)
    if not manuscript.strip():
        ms_rel = legacy_draft_manuscript_rel()
        manuscript = _read_text(root / ms_rel)
    if not manuscript.strip():
        ms_rel = confirmed_manuscript_rel()
        manuscript = _read_text(root / ms_rel)
    parts: list[dict[str, Any]] = []
    if manuscript.strip():
        parts.append(
            _part(
                key="manuscript",
                label="正文",
                text=manuscript,
                kind="manuscript",
                path=_public_rel(root, root / ms_rel),
            )
        )
    from app.writing.canon import CONFIRMED_MD, format_book_confirmed, publish_confirmed_md

    confirmed = format_book_confirmed(workspace_root=root)
    if confirmed.strip():
        publish_confirmed_md(workspace_root=root)
        parts.append(
            _part(
                key="canon",
                label="已确认",
                text=confirmed,
                kind="canon",
                path=CONFIRMED_MD,
            )
        )
    if outline.strip():
        parts.append(
            _part(
                key="outline",
                label="大纲",
                text=outline,
                kind="outline",
                path=_public_rel(root, outline_path),
            )
        )
    from app.writing.outline_store import list_chapter_rels, list_volume_rels

    for rel in list_volume_rels(root):
        body = _read_text(root / rel)
        if not body.strip():
            continue
        parts.append(
            _part(
                key=rel,
                label="卷纲",
                text=body,
                kind="volume",
                path=rel,
            )
        )
    for rel in list_chapter_rels(root):
        body = _read_text(root / rel)
        if not body.strip():
            continue
        parts.append(
            _part(
                key=rel,
                label="章便条",
                text=body,
                kind="chapter",
                path=rel,
            )
        )
    title = _first_heading(outline) or _first_heading(manuscript) or "未命名"
    empty = not parts
    if empty:
        title = "还没有书"
    from app.writing.story_state import load_story_state, consistency_flags
    from app.writing.manuscript import list_section_ids, extract_section
    from app.writing.reread import load_retcon_pending
    from app.writing.taste import load_taste_marks

    state = load_story_state(workspace_root=root)
    flags: list[dict[str, Any]] = []
    ids = list_section_ids(manuscript) if manuscript else []
    last_id = ids[-1] if ids else ""
    if last_id:
        flags.extend(
            consistency_flags(
                extract_section(manuscript, last_id) if manuscript else "",
                section_id=last_id,
                workspace_root=root,
            )
        )
    editor_flags: list[dict[str, Any]] = []
    editor_dir = root / ".agent" / "work" / "editor"
    if editor_dir.is_dir():
        files = sorted(editor_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            try:
                payload = json.loads(files[0].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                editor_flags = list(payload.get("flags") or [])
                keep = list(payload.get("keep") or [])
            else:
                keep = []
        else:
            keep = []
    else:
        keep = []
    console = False
    canon_promises: list[dict[str, Any]] = []
    if not console:
        from app.writing.canon import load_canon

        canon_promises = [
            fact
            for fact in load_canon(workspace_root=root).get("facts") or []
            if isinstance(fact, dict)
            and fact.get("kind") == "promise"
            and fact.get("status") == "active"
        ]
    return {
        "title": title,
        "empty": empty,
        "parts": parts,
        "wild_cards": list(state.get("wild_cards") or []) if console else [],
        "swerves": list(state.get("swerves") or []) if console else [],
        "consistency_flags": flags,
        "identity": state.get("identity") or {},
        "reader_ledger": state.get("reader_ledger") or {} if console else {},
        "promises": state.get("promises") or [] if console else canon_promises,
        "deferred": state.get("deferred") or [] if console else [],
        "editor_flags": editor_flags,
        "editor_keep": keep,
        "taste_marks": load_taste_marks(workspace_root=root)[-12:],
        "retcon_pending": load_retcon_pending(workspace_root=root),
    }


def _unlink_file(root: Path, rel: str, cleared: list[str], tag: str) -> None:
    path = (root / rel).resolve()
    if not _is_under(root, path) or not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        return
    if tag not in cleared:
        cleared.append(tag)


def _wipe_dir_files(root: Path, rel: str, cleared: list[str], tag: str) -> None:
    path = (root / rel).resolve()
    if not path.exists() or not _is_under(root, path):
        return
    if path.is_file():
        _unlink_file(root, rel, cleared, tag)
        return
    try:
        shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    if tag not in cleared:
        cleared.append(tag)


def discard_writing_book(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """扔掉这本书：用户稿 + 侧车。不动 seed、资料库上传、会话。"""
    root = _workspace(workspace_root)
    cleared: list[str] = []
    _unlink_file(root, "outline.md", cleared, "outline")
    _unlink_file(root, "confirmed.md", cleared, "manuscript")
    for rel in (
        draft_manuscript_rel(),
        legacy_draft_manuscript_rel(),
        confirmed_manuscript_rel(),
    ):
        _unlink_file(root, rel, cleared, "manuscript")
    _wipe_dir_files(root, ARCHIVE_DIR, cleared, "archives")
    drafts = root / "drafts"
    if drafts.is_dir() and _is_under(root, drafts):
        for fp in drafts.iterdir():
            if fp.is_file() and fp.suffix == ".md":
                _unlink_file(root, f"drafts/{fp.name}", cleared, "manuscript")
    from app.writing.cards import cards_root

    cards_dir = cards_root(workspace_root=root)
    if cards_dir.is_dir() and _is_under(root, cards_dir):
        _wipe_dir_files(root, str(cards_dir.relative_to(root)), cleared, "people")
    from app.writing.signals.beats import clear_local_beats

    beats_path = root / ".agent" / "work" / "local_beats.json"
    if beats_path.is_file():
        clear_local_beats(workspace_root=root)
        _unlink_file(root, ".agent/work/local_beats.json", cleared, "beats")
    _unlink_file(root, ".agent/work/opening_ponds.json", cleared, "outline")
    _unlink_file(root, ".agent/work/opening_ponds_rejected.jsonl", cleared, "outline")
    _unlink_file(root, ".agent/work/committed_pond.json", cleared, "outline")
    _unlink_file(root, ".agent/work/story_state.json", cleared, "outline")
    _unlink_file(root, ".agent/work/story_state.md", cleared, "outline")
    _unlink_file(root, ".agent/work/author_notes.md", cleared, "outline")
    _unlink_file(root, ".agent/work/author_state.md", cleared, "outline")
    _unlink_file(root, ".agent/work/author_state_stance.jsonl", cleared, "outline")
    _wipe_dir_files(root, ".agent/work/editor", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/taste", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/retcon", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/editor_notes", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/surface", cleared, "beats")
    _unlink_file(root, ".agent/work/surface_index.json", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/history", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/turns", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/drafts", cleared, "manuscript")
    _unlink_file(root, ".agent/work/canon_facts.json", cleared, "manuscript")
    _unlink_file(root, ".agent/work/ledger.jsonl", cleared, "manuscript")
    _unlink_file(root, ".agent/work/planning_mode", cleared, "outline")
    _unlink_file(root, ".agent/work/voice_choice", cleared, "outline")
    _wipe_dir_files(root, ".agent/work/commitments", cleared, "manuscript")
    if clear_style_lock(workspace_root=root) and "outline" not in cleared:
        cleared.append("outline")
    return {
        "ok": True,
        "cleared": cleared,
        "book": load_writing_book(workspace_root=root),
    }
