"""Accidental large prose duplicates: detect, collapse, reject worsening patches.

Broadcast rewrite of short exact spans (single ``\\n`` within one paragraph) is
unchanged. Collapse targets blank-line-separated paragraphs with enough visible
chars to be accidental paste islands, not refrain words like 「咚。」.
"""

from __future__ import annotations

import re
from typing import Any

from app.writing.text_metrics import visible_chars

# Below this, exact para repeats are left alone (short beats / refrain).
DUP_PARA_MIN_VISIBLE = 28

_PARA_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    body = text or ""
    if not body:
        return []
    return [p for p in _PARA_SPLIT.split(body) if p.strip() != ""]


def excess_large_duplicate_paragraphs(
    text: str, *, min_visible: int = DUP_PARA_MIN_VISIBLE
) -> int:
    """How many extra copies of large paragraphs exist (total − unique)."""
    seen: dict[str, int] = {}
    for para in split_paragraphs(text):
        key = para.strip()
        if visible_chars(key) < min_visible:
            continue
        seen[key] = seen.get(key, 0) + 1
    return sum(n - 1 for n in seen.values() if n > 1)


def collapse_duplicate_paragraphs(
    text: str, *, min_visible: int = DUP_PARA_MIN_VISIBLE
) -> tuple[str, int]:
    """Keep first large exact paragraph; drop later copies. Returns (text, removed)."""
    body = text or ""
    if not body.strip():
        return body, 0
    seen: set[str] = set()
    out: list[str] = []
    removed = 0
    for part in _PARA_SPLIT.split(body):
        stripped = part.strip()
        if not stripped:
            continue
        if visible_chars(stripped) >= min_visible:
            if stripped in seen:
                removed += 1
                continue
            seen.add(stripped)
        out.append(stripped)
    if removed == 0:
        return body, 0
    joined = "\n\n".join(out)
    if body.endswith("\n") and not joined.endswith("\n"):
        joined += "\n"
    return joined, removed


def collapse_prose_duplicates(
    document: str,
    *,
    section_id: str = "",
    min_visible: int = DUP_PARA_MIN_VISIBLE,
) -> tuple[str, int]:
    """Collapse large para dups in one chapter body (or whole document)."""
    from app.writing.manuscript import extract_section, list_section_ids, upsert_section

    sid = (section_id or "").strip()
    if sid and sid in list_section_ids(document):
        body = extract_section(document, sid) or ""
        new_body, removed = collapse_duplicate_paragraphs(
            body, min_visible=min_visible
        )
        if not removed:
            return document, 0
        return upsert_section(document, sid, new_body), removed
    return collapse_duplicate_paragraphs(document, min_visible=min_visible)


def _body_without_first_span(body: str, old_text: str) -> str:
    old = old_text or ""
    if not old:
        return body
    idx = body.find(old)
    if idx < 0:
        return body
    return body[:idx] + body[idx + len(old) :]


def patch_worsens_duplicate(
    body: str,
    old_text: str,
    new_text: str,
    *,
    min_visible: int = DUP_PARA_MIN_VISIBLE,
) -> str | None:
    """Return error message when patch would re-paste or raise large-dup excess.

    Deletion (``new_text`` empty / whitespace) is always allowed.
    Small surgical edits below ``min_visible`` are not gated here.
    """
    new = (new_text or "").strip()
    if not new:
        return None
    if visible_chars(new) < min_visible:
        return None
    existing = body or ""
    old = old_text or ""
    remainder = _body_without_first_span(existing, old)
    if new in remainder:
        return (
            "patch_worsens_duplicate: new_text already present elsewhere; "
            "delete the extra copy (new_text=\"\") or collapse, do not paste again"
        )
    if old and old in existing:
        simulated = existing.replace(old, new_text or "", 1)
    else:
        simulated = existing
    before = excess_large_duplicate_paragraphs(existing, min_visible=min_visible)
    after = excess_large_duplicate_paragraphs(simulated, min_visible=min_visible)
    if after > before:
        return (
            "patch_worsens_duplicate: apply would increase large paragraph duplicates; "
            "delete extras (new_text=\"\") or rewrite a unique span"
        )
    return None


def reject_worsening_prose_patch(
    body: str,
    old_text: str,
    new_text: str,
    *,
    path: str = "",
) -> dict[str, Any] | None:
    """Error payload for propose/apply, or None when allowed."""
    reason = patch_worsens_duplicate(body, old_text, new_text)
    if not reason:
        return None
    payload: dict[str, Any] = {
        "status": "error",
        "error": "patch_worsens_duplicate",
        "applies": False,
        "summary": reason,
        "old_text": old_text,
        "new_text": new_text,
    }
    if path:
        payload["path"] = path
    return payload
