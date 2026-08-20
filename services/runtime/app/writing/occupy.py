"""New standalone piece vs continue the current manuscript (no LLM).

A Work owns one live ``drafts/manuscript.md``. ``draft_section`` upserts chapters
into that file, which is correct for 续写 / 下一章 and wrong when the user asks
for an unrelated 一篇. Occupied files are archived under ``drafts/archive/``
instead of asking the user to delete them.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.writing.manuscript import (
    confirmed_manuscript_rel,
    draft_manuscript_rel,
    legacy_draft_manuscript_rel,
    list_section_ids,
)
from app.writing.text_metrics import visible_chars

ARCHIVE_DIR = "drafts/archive"

_CONTINUE_RE = re.compile(
    r"接着写|继续写|往下写|续写|下一章|下章|"
    r"这一章|本章|"
    r"写第|[第][一二三四五六七八九十百千零〇两\d]+章|"
    r"(?:再|又|还)?写一章|加一章|"
    r"改这|润色这|"
    r"把这[篇章节]|把昨天|把上次"
)

_NEW_PIECE_RE = re.compile(
    r"(?:另|重新|新|再|换)(?:开|写)一篇|"
    r"另开一篇|新开一篇|再来一篇|换个故事|换一篇|"
    r"写一篇|写个故事|写一个故事|写篇(?:新的)?故事|写个短篇|写一篇短篇|"
    r"write a (?:new )?story|\bnew story\b",
    re.I,
)

_OUTLINE_ASK_RE = re.compile(r"章纲|大纲|目录|提纲")
_NEW_BOOK_OUTLINE_RE = re.compile(r"另|新开|再来|换一篇|换个故事")
_FRESH_TOKENS = frozenset({"fresh", "new", "replace_doc", "1", "true", "yes"})
_UPSERT_TOKENS = frozenset({"upsert", "continue", "append", "0", "false", "no"})


def wants_new_piece(user_text: str) -> bool:
    """True for a standalone new story, not 续写 / 第N章 of the current file."""
    text = (user_text or "").strip()
    if not text:
        return False
    if _CONTINUE_RE.search(text):
        return False
    if _NEW_PIECE_RE.search(text) is None:
        return False
    if _OUTLINE_ASK_RE.search(text) and not _NEW_BOOK_OUTLINE_RE.search(text):
        return False
    return True


def manuscript_is_occupied(text: str) -> bool:
    """Any keepable prose — H1 chapters or an unstructured blob."""
    blob = text or ""
    if visible_chars(blob) <= 0:
        return False
    ids = list_section_ids(blob)
    if ids:
        return True
    return visible_chars(blob) >= 40


def parse_occupy_arg(raw: object | None) -> str | None:
    """Return ``fresh`` / ``upsert`` / None (infer from the user text)."""
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if not token:
        return None
    if token in _FRESH_TOKENS:
        return "fresh"
    if token in _UPSERT_TOKENS:
        return "upsert"
    return None


def should_occupy_fresh(
    *,
    occupy_arg: object | None,
    user_text: str,
    already_fresh_this_turn: bool,
    occupied: bool,
) -> bool:
    """First write of an unrelated new piece onto an occupied manuscript."""
    if already_fresh_this_turn:
        return False
    parsed = parse_occupy_arg(occupy_arg)
    if parsed == "upsert":
        return False
    if parsed == "fresh":
        return occupied
    if not occupied:
        return False
    return wants_new_piece(user_text)


def next_archive_rel(stem: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (stem or "draft").strip()) or "draft"
    base = f"{ARCHIVE_DIR}/{stamp}-{safe}.md"
    from app.tools.core.paths import _resolve_path

    if not _resolve_path(base).exists():
        return base
    for idx in range(2, 40):
        cand = f"{ARCHIVE_DIR}/{stamp}-{safe}-{idx}.md"
        if not _resolve_path(cand).exists():
            return cand
    return f"{ARCHIVE_DIR}/{stamp}-{safe}-{uuid4().hex[:6]}.md"


def archive_workspace_file(rel: str) -> str | None:
    """Copy an occupied file to ``drafts/archive/``. Caller decides whether to unlink."""
    from app.tools.core.paths import _resolve_path

    normalized = (rel or "").strip().lstrip("/")
    if not normalized:
        return None
    src = _resolve_path(normalized)
    if not src.is_file():
        return None
    try:
        text = src.read_text(encoding="utf-8")
    except OSError:
        return None
    if not manuscript_is_occupied(text):
        return None
    dest_rel = next_archive_rel(Path(normalized).stem)
    dest = _resolve_path(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest_rel


def archive_occupied_writing_docs(*, layout: str = "monofile") -> list[str]:
    """Archive live manuscript + outline so a new piece can own the work surface.

    Returns archived relative paths. Unlinks the live draft/confirmed
    manuscript and outline after copy so the new piece owns the work surface.
    """
    archived: list[str] = []
    from app.tools.core.paths import _resolve_path

    if layout == "sections":
        drafts = _resolve_path("drafts")
        if drafts.is_dir():
            for path in sorted(drafts.iterdir()):
                if path.is_file() and path.suffix == ".md" and not path.name.startswith("."):
                    rel = f"drafts/{path.name}"
                    copied = archive_workspace_file(rel)
                    if copied:
                        archived.append(copied)
                        try:
                            path.unlink()
                        except OSError:
                            pass
    else:
        for rel in (
            draft_manuscript_rel(),
            legacy_draft_manuscript_rel(),
            confirmed_manuscript_rel(),
        ):
            copied = archive_workspace_file(rel)
            if copied:
                archived.append(copied)
                try:
                    _resolve_path(rel).unlink()
                except OSError:
                    pass

    outline_copied = archive_workspace_file("outline.md")
    if outline_copied:
        archived.append(outline_copied)
        try:
            _resolve_path("outline.md").unlink()
        except OSError:
            pass
    return archived


def occupy_result_fields(archived: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {"occupy": "fresh"}
    if archived:
        fields["archived"] = archived
        fields["summary"] = (
            "先前成稿与当前这篇无关，已归档到 "
            + "、".join(f"`{p}`" for p in archived)
            + "。本文件现在只放这一篇。"
        )
    return fields
