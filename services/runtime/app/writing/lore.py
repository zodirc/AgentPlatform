"""开篇 lore dump 检测。"""

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
    """是否开篇章。
    
    参数:
        section_id。
    
    返回:
        bool。"""
    sid = (section_id or "").strip()
    if not sid:
        return True
    from app.writing.manuscript import human_section_title

    if human_section_title(sid) == "第一章":
        return True
    return sid.lower() in _OPENING_IDS


def has_lore_dump(text: str) -> bool:
    """是否有 lore dump。
    
    参数:
        text。
    
    返回:
        bool。"""
    return bool(find_lore_span(text))


def find_lore_span(text: str, *, max_chars: int = 360) -> str:
    """lore span。
    
    参数:
        text/max_chars。
    
    返回:
        str。"""
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
    """lore 软事实。
    
    参数:
        content/section_id。
    
    返回:
        dict。"""
    from app.writing.text_metrics import visible_chars

    if not is_opening_section(section_id):
        return {}
    text = content or ""
    if visible_chars(text) < _MIN_VISIBLE:
        return {}
    if not has_lore_dump(text):
        return {}
    return {"lore_dump": True}
