"""写作「这本书」：用户看见的稿件对象，不是目录树。

Inventory 含大纲、正文、素材卡（含 pending）、记下的拍、旧稿归档。
扔掉整本时清这些用户内容与 `.agent/work` 侧车；不动资料库、种子语料、会话。
"""

from __future__ import annotations

import json
import re
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
_PENDING_STEM_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f-]{8,}_(.+)$", re.I)
_KIND_LABELS = {
    "character": "人物",
    "plot": "情节",
    "style": "风格",
    "general": "设定",
}


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


def _card_display_title(path: Path, parsed: str) -> str:
    stem = path.stem
    match = _PENDING_STEM_RE.match(stem)
    guessed = match.group(1).strip() if match else ""
    if guessed and (parsed == stem or parsed.startswith("20") or not parsed):
        return guessed
    return parsed or guessed or stem


def _load_cards(root: Path) -> list[dict[str, Any]]:
    from app.writing.cards import (
        _card_title,
        _infer_kind,
        _parse_frontmatter,
        cards_root,
    )

    cards_dir = cards_root(workspace_root=root)
    if not cards_dir.is_dir() or not _is_under(root, cards_dir):
        return []
    out: list[dict[str, Any]] = []
    for idx, fp in enumerate(sorted(cards_dir.rglob("*.md"))):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        if not _is_under(root, fp):
            continue
        raw = _read_text(fp)
        meta, body = _parse_frontmatter(raw)
        kind = _infer_kind(fp, meta)
        title = _card_display_title(fp, _card_title(fp, meta, body or raw))
        kind_label = _KIND_LABELS.get(kind, "设定")
        out.append(
            _part(
                key=f"card:{idx}",
                label=f"{kind_label} · {title}",
                text=body or raw,
                kind=kind,
                path=_public_rel(root, fp),
            )
        )
    return out


def _load_beats(root: Path) -> list[dict[str, Any]]:
    from app.writing.work_mode import fragment_label

    path = root / ".agent" / "work" / "local_beats.json"
    raw = _read_text(path)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = payload.get("beats") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        frag = str(item.get("fragment") or "mixed")
        label = fragment_label(frag)
        out.append(_part(key=f"beat:{idx}", label=label, text=text, kind="beat"))
    return out


def _load_archives(root: Path) -> list[dict[str, Any]]:
    archive = root / ARCHIVE_DIR
    if not archive.is_dir() or not _is_under(root, archive):
        return []
    out: list[dict[str, Any]] = []
    for idx, fp in enumerate(sorted(archive.glob("*.md"))):
        if not fp.is_file():
            continue
        text = _read_text(fp)
        title = _first_heading(text) or fp.stem
        out.append(
            _part(
                key=f"archive:{idx}",
                label=f"旧稿 · {title}",
                text=text,
                kind="archive",
                path=_public_rel(root, fp),
            )
        )
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
    cards = _load_cards(root)
    beats = _load_beats(root)
    archives = _load_archives(root)
    parts: list[dict[str, Any]] = []
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
    parts.extend(cards)
    parts.extend(beats)
    parts.extend(archives)
    title = _first_heading(outline) or _first_heading(manuscript) or "未命名"
    empty = not parts
    if empty:
        title = "还没有书"
    return {
        "title": title,
        "empty": empty,
        "parts": parts,
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
    _wipe_dir_files(root, ".agent/work/history", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/turns", cleared, "beats")
    _wipe_dir_files(root, ".agent/work/drafts", cleared, "manuscript")
    if clear_style_lock(workspace_root=root) and "outline" not in cleared:
        cleared.append("outline")
    return {
        "ok": True,
        "cleared": cleared,
        "book": load_writing_book(workspace_root=root),
    }
