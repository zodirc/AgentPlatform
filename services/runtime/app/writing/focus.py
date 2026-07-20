"""Writing focus / work-surface loading (docs/24 WT1). Pure heuristics — no LLM."""

from __future__ import annotations

import re
from pathlib import Path

from app.settings import settings
from app.writing.manuscript import (
    clip_text,
    extract_section,
    list_section_ids,
    load_manuscript_doc,
    previous_section_id,
)

_CHAPTER_ARABIC = re.compile(
    r"(?:第\s*([0-9０-９]+)\s*章|(?:chapter|ch|section)\s*[_\-]?\s*([0-9]+)|(?:^|\b)ch([0-9]+)\b)",
    re.I,
)
_CHAPTER_CN = re.compile(r"第\s*([一二三四五六七八九十百零两]+)\s*章")
_CONTINUE = re.compile(r"(接着写|继续写|往下写|续写|下一章|下章)")

_CN_NUM = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _cn_to_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    # normalize fullwidth digits
    normalized = "".join(chr(ord(c) - 0xFEE0) if "０" <= c <= "９" else c for c in token)
    if normalized.isdigit():
        return int(normalized)
    if token in _CN_NUM:
        return _CN_NUM[token]
    if token.startswith("十"):
        rest = token[1:]
        return 10 + (_CN_NUM.get(rest, 0) if rest else 0)
    if "十" in token:
        left, _, right = token.partition("十")
        return _CN_NUM.get(left, 0) * 10 + _CN_NUM.get(right, 0)
    return None


def _candidate_ids_for_number(n: int, available: list[str]) -> list[str]:
    opts = [f"ch{n}", f"0{n}" if n < 10 else str(n), str(n), f"{n:02d}"]
    out: list[str] = []
    for opt in opts:
        if opt in available and opt not in out:
            out.append(opt)
    # fuzzy: available id ending with number
    for sid in available:
        if re.search(rf"(?:^|[^0-9])0*{n}$", sid) and sid not in out:
            out.append(sid)
    return out


def infer_focus_section_id(message: str, available: list[str]) -> str | None:
    text = (message or "").strip()
    if not text:
        return available[-1] if available else None

    # Exact id mention
    for sid in sorted(available, key=len, reverse=True):
        if re.search(rf"(?:^|\b){re.escape(sid)}(?:\b|$)", text, re.I):
            return sid

    m = _CHAPTER_ARABIC.search(text)
    if m:
        raw = next(g for g in m.groups() if g)
        n = _cn_to_int(raw)
        if n is not None:
            hits = _candidate_ids_for_number(n, available)
            if hits:
                return hits[0]
            return f"ch{n}"

    m2 = _CHAPTER_CN.search(text)
    if m2:
        n = _cn_to_int(m2.group(1))
        if n is not None:
            hits = _candidate_ids_for_number(n, available)
            if hits:
                return hits[0]
            return f"ch{n}"

    if _CONTINUE.search(text):
        return available[-1] if available else None

    return None


def wants_full_manuscript_read(message: str = "", *, full_flag: bool = False) -> bool:
    if full_flag:
        return True
    text = message or ""
    keys = ("通读", "全文", "整本", "全书检查", "全文检查", "whole book", "entire manuscript")
    return any(k in text.lower() if k.isascii() else k in text for k in keys)


def build_work_surface_block(
    message: str,
    *,
    workspace_root: Path | None = None,
    max_chars: int | None = None,
    prev_tail_chars: int | None = None,
    focus_max_chars: int | None = None,
) -> str:
    """Short focus+prev block for writing system prompt (docs/24 WT1b)."""
    budget = max_chars if max_chars is not None else settings.writing_work_surface_max_chars
    prev_n = prev_tail_chars if prev_tail_chars is not None else settings.writing_prev_tail_chars
    focus_n = focus_max_chars if focus_max_chars is not None else settings.writing_focus_max_chars
    budget = max(200, int(budget))

    doc, rel = load_manuscript_doc(workspace_root)
    available = list_section_ids(doc) if doc else []
    focus = infer_focus_section_id(message, available)

    lines = [
        "## Work surface",
        f"Source: `{rel}` (chapter blocks only — not the whole book in context).",
    ]
    if not focus:
        lines.append("- focus: (undetected; pass `section_id` to `read_file` on the manuscript)")
        if available:
            lines.append(f"- present: {', '.join(available[:20])}")
        text = "\n".join(lines)
        return text if len(text) <= budget else text[: budget - 1] + "…"

    lines.append(f"- focus: `{focus}`")
    prev = previous_section_id(available, focus)
    body_parts: list[str] = []

    if prev:
        prev_body = extract_section(doc, prev) or ""
        tail = prev_body[-prev_n:] if prev_body else ""
        if tail:
            body_parts.append(f"### Previous tail (`{prev}`)\n{tail}")
            lines.append(f"- prev_tail: `{prev}` ({len(tail)} chars)")

    focus_body = extract_section(doc, focus)
    if focus_body is None:
        lines.append(f"- focus body: (new section `{focus}` — not on disk yet)")
    else:
        clipped, was_clipped = clip_text(focus_body, focus_n)
        body_parts.append(f"### Focus (`{focus}`)\n{clipped}")
        note = f"{len(focus_body)} chars"
        if was_clipped:
            note += ", clipped with visible omission"
        lines.append(f"- focus body: {note}")

    header = "\n".join(lines)
    body = "\n\n".join(body_parts)
    combined = f"{header}\n\n{body}" if body else header
    if len(combined) <= budget:
        return combined
    # Prefer keeping header + truncated body
    remain = budget - len(header) - 2
    if remain < 80:
        return header[: budget - 1] + "…"
    return f"{header}\n\n{body[: remain - 1]}…"


def build_writing_bookmark(
    *,
    focus: str | None,
    sections: list[str],
    outline_toc: str = "",
    notes: str = "",
    last_user: str = "",
) -> dict[str, object]:
    from app.writing.manuscript import confirmed_manuscript_rel, draft_manuscript_rel

    return {
        "manuscript": confirmed_manuscript_rel(),
        "draft": draft_manuscript_rel(),
        "focus": focus or "",
        "sections_present": sections[:40],
        "outline_toc": outline_toc[:800],
        "notes": notes[:500],
        "last_user": last_user[:800],
    }


def format_writing_bookmark(bookmark: dict[str, object]) -> str:
    sections = bookmark.get("sections_present") or []
    if isinstance(sections, list):
        sec = ", ".join(str(s) for s in sections[:24])
    else:
        sec = str(sections)
    lines = [
        "[writing bookmark]",
        f"manuscript: {bookmark.get('manuscript', 'manuscript.md')} | "
        f"draft: {bookmark.get('draft', '.agent/work/drafts/manuscript.md')}",
        f"focus: {bookmark.get('focus') or '(none)'}",
        f"sections_present: {sec or '(none)'}",
    ]
    toc = str(bookmark.get("outline_toc") or "").strip()
    if toc:
        lines.append(f"outline:\n{toc}")
    notes = str(bookmark.get("notes") or "").strip()
    if notes:
        lines.append(f"notes: {notes}")
    last_user = str(bookmark.get("last_user") or "").strip()
    if last_user:
        lines.append(f"last_user:\n{last_user}")
    return "\n".join(lines)


def outline_toc_snippet(workspace_root: Path | None = None, *, max_chars: int = 600) -> str:
    root = Path(workspace_root or settings.workspace_root).resolve()
    path = root / "outline.md"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = []
    for line in text.splitlines():
        if line.startswith("#") or line.strip().startswith("-") or line.strip().startswith("*"):
            lines.append(line.rstrip())
        if sum(len(x) + 1 for x in lines) >= max_chars:
            break
    blob = "\n".join(lines)
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"
