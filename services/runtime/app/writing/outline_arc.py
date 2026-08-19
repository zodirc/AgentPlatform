"""Long-outline arrangement facts: spine, peak placement, peak flood.

Soft facts only. Callers never mutate disk. Short TOC / novella asks skip.
"""

from __future__ import annotations

import re
from typing import Any

from app.writing.opening import institution_before_place
from app.writing.text_metrics import wants_outline_toc_only

_MD_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.M)
_CHAPTER_LINE = re.compile(
    r"^第[一二三四五六七八九十百千零〇两\d]+章\b.*$",
    re.M,
)
_SHORT_BOOK = re.compile(r"短篇|中篇")
_PEAK = re.compile(
    r"高潮|到顶|摊牌|决战|翻脸|决裂|揭穿|对质|撑不住|出事了|本卷顶点|全书顶点|压力到顶"
)
_SPINE = re.compile(r"主线|副线|主次|谁要|挡着|通过线")

_MIN_CHAPTERS = 6
_SPINE_CHARS = 500
_JOB_CHARS = 500
_PEAK_FLOOD_RATIO = 0.4
_PEAK_FLOOD_MIN = 3
_CH1_HEAD = re.compile(r"^#{1,3}\s*第一章\b.*$", re.M)
_CH1_RANGE = re.compile(r"^1\s*[—\-–至到]\s*\d+[：:].+$", re.M)


def _chapter_spans(md: str) -> list[tuple[str, str]]:
    """Return [(title, body), ...] for outline chapters."""
    text = md or ""
    spans: list[tuple[int, int, str]] = []
    for match in _MD_HEADING.finditer(text):
        spans.append((match.start(), match.end(), match.group(1).strip()))
    if not spans:
        for match in _CHAPTER_LINE.finditer(text):
            spans.append((match.start(), match.end(), match.group(0).strip()))
    if not spans:
        return []
    out: list[tuple[str, str]] = []
    for i, (_start, end, title) in enumerate(spans):
        body_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        out.append((title, text[end:body_end].strip()))
    return out


def _preamble(md: str) -> str:
    text = md or ""
    first = _MD_HEADING.search(text) or _CHAPTER_LINE.search(text)
    if first is None:
        return text.strip()
    return text[: first.start()].strip()


def extract_outline_spine(md: str, *, max_chars: int = _SPINE_CHARS) -> str:
    """Preamble before the first chapter heading (through-line lives here)."""
    blob = _preamble(md)
    if not blob:
        return ""
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"


def extract_opening_outline_blob(md: str, *, max_chars: int = 800) -> str:
    """Chapter-1 card / 1—N line / 「第一章只写…」 — where the entry is decided."""
    parts: list[str] = []
    job = extract_outline_job(md, "ch1") or extract_outline_job(md, "第一章")
    if job:
        parts.append(job)
    text = md or ""
    for match in _CH1_HEAD.finditer(text):
        start = match.end()
        nxt = re.search(r"^#{1,3}\s+", text[start:], re.M)
        body = text[start : start + nxt.start()] if nxt else text[start : start + 600]
        parts.append(match.group(0) + "\n" + body)
    for match in _CH1_RANGE.finditer(text):
        parts.append(match.group(0))
    for match in re.finditer(r"第一章.{0,48}", text):
        parts.append(match.group(0))
    blob = "\n".join(parts).strip()
    if not blob:
        return ""
    return blob if len(blob) <= max_chars else blob[: max_chars - 1] + "…"


def extract_outline_job(
    md: str,
    section_id: str,
    *,
    max_chars: int = _JOB_CHARS,
) -> str:
    """Chapter blurb from outline.md matching chN / 第N章."""
    from app.writing.manuscript import human_section_title

    sid = (section_id or "").strip()
    if not sid:
        return ""
    title_want = human_section_title(sid)
    for title, body in _chapter_spans(md):
        if title == sid or title == title_want:
            hit = body
        elif sid.lower() in title.lower() or title_want in title:
            hit = body
        else:
            continue
        if not hit:
            return ""
        return hit if len(hit) <= max_chars else hit[: max_chars - 1] + "…"
    return ""


def outline_arc_fields(md: str, user_text: str) -> dict[str, Any]:
    """Flag missing through-line / peak, or too many peaks. Empty if N/A."""
    if wants_outline_toc_only(user_text):
        return {}
    if _SHORT_BOOK.search(user_text or ""):
        return {}
    chapters = _chapter_spans(md)
    n = len(chapters)
    opening_notes: list[str] = []
    if institution_before_place(extract_opening_outline_blob(md)):
        opening_notes.append(
            "第一章入口写成了机构专名（宗/派）。先写可站的地方（镇、路、田、谁管这块地），"
            "机构名让人物后口带出；身世仍不要写成提要。"
        )

    if n < _MIN_CHAPTERS:
        if not opening_notes:
            return {}
        return {
            "outline_institution_first": True,
            "summary_suffix": "长篇编排：" + "".join(opening_notes),
        }

    full = md or ""
    peak_chapters = [
        title for title, body in chapters if _PEAK.search(title) or _PEAK.search(body)
    ]
    has_spine = bool(_SPINE.search(full))
    notes: list[str] = list(opening_notes)
    out: dict[str, Any] = {"outline_chapters": n}
    if opening_notes:
        out["outline_institution_first"] = True

    if not has_spine:
        out["outline_no_spine"] = True
        notes.append("未点明主线/副线（谁要什么、谁挡着）。")
    if not peak_chapters:
        out["outline_no_peak"] = True
        notes.append("未标本卷压力到顶的一处（高潮/摊牌/撑不住均可）。")
    elif (
        len(peak_chapters) >= _PEAK_FLOOD_MIN
        and len(peak_chapters) / n > _PEAK_FLOOD_RATIO
    ):
        out["outline_peak_flood"] = True
        out["peak_chapters"] = peak_chapters[:12]
        notes.append(
            f"{len(peak_chapters)}/{n} 章都在写高潮，主次被抹平。"
            "多数章应是过日子或加压，高潮只落一处（或中途翻转+卷末）。"
        )

    if not notes:
        return {}
    out["summary_suffix"] = (
        "长篇编排："
        + "".join(notes)
        + "章末可以停在日子上，不等于全书没有顶点。同轮补进纲里后再结束。"
    )
    return out
