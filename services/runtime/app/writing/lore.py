"""Detect first-chapter lore dump: N年前 + 失踪/尸体 as a synopsis paragraph.

Soft facts only. Not a chapter-count detector. Callers never mutate disk.
"""

from __future__ import annotations

import re
from typing import Any

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_YEARS_AGO = re.compile(r"(?:[一二三四五六七八九十百零两\d]+多?)\s*年前")
_BIO = re.compile(r"(?:失踪|没回家|找不到尸体|没有找到尸体|唯一没有找到)")
_MIN_VISIBLE = 80
_OPENING_IDS = {"intro", "prologue", "楔子"}


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENT_SPLIT.split(text or "") if part.strip()]


def is_opening_section(section_id: str) -> bool:
    sid = (section_id or "").strip()
    if not sid:
        return True
    from app.writing.manuscript import human_section_title

    if human_section_title(sid) == "第一章":
        return True
    return sid.lower() in _OPENING_IDS


def has_lore_dump(text: str) -> bool:
    """True when 「N年前」 is paired with 失踪/没回家/尸体 in this or the next sentence."""
    return bool(find_lore_span(text))


def find_lore_span(text: str, *, max_chars: int = 360) -> str:
    """Exact slice covering the first N年前 + 失踪/尸体 pair."""
    sents = _sentences(text)
    body = text or ""
    for i, sent in enumerate(sents):
        if not _YEARS_AGO.search(sent):
            continue
        nxt = sents[i + 1] if i + 1 < len(sents) else ""
        if not (_BIO.search(sent) or _BIO.search(nxt)):
            continue
        idx = body.find(sent)
        if idx < 0:
            blob = sent if _BIO.search(sent) or not nxt else f"{sent}{nxt}"
            return blob[:max_chars]
        end_token = sent if _BIO.search(sent) or not nxt else nxt
        end = body.find(end_token, idx)
        if end < 0:
            end = idx + len(sent)
        else:
            end += len(end_token)
        span = body[idx:end]
        return span if len(span) <= max_chars else span[:max_chars]
    return ""


def lore_fields(content: str, section_id: str = "") -> dict[str, Any]:
    """Attach to draft_section. Opening chapter only — later chapters may recap."""
    from app.writing.text_metrics import visible_chars

    if not is_opening_section(section_id):
        return {}
    text = content or ""
    if visible_chars(text) < _MIN_VISIBLE:
        return {}
    if not has_lore_dump(text):
        return {}
    return {"lore_dump": True}
