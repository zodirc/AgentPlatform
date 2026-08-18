"""Deterministic length / outline-thin facts for writing tool results.

Counts match writing/system.md: 「N 字」= 实体文字 (non-whitespace), not raw
``len()``. No LLM. Signals only — callers never mutate disk because of these.
"""

from __future__ import annotations

import re

LENGTH_SHORT_RATIO = 0.85
OUTLINE_MIN_VISIBLE = 200

# Prefer these stems when several numbers appear in one Turn message.
_PREFERRED_QUOTA = re.compile(
    r"(?:不少于|至少|约|大约|写了?)\s*(\d{2,6})\s*字"
)
_AROUND_QUOTA = re.compile(r"(\d{2,6})\s*字(?:左右|以上)")
_ANY_QUOTA = re.compile(r"(\d{2,6})\s*字")

_TOC_MARKERS = (
    "只要目录",
    "标题列表",
    "只要标题",
    "简略",
    "短目录",
    "短纲",
)

# Short-outline ask. Do not treat 「短篇」as TOC-only.
_SHORT_OUTLINE_ASK = re.compile(
    r"(?:只要|要)短|"
    r"写短(?!篇)|"
    r"短(?:一点|一些|点)|"
    r"短(?:大纲|目录|纲)|"
    r"(?:^|[/\s])短(?:$|[\s，。])"
)

_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.M)
_CHAPTER_LINE = re.compile(
    r"^第[一二三四五六七八九十百千零〇两\d]+章\b.*$",
    re.M,
)


def visible_chars(text: str) -> int:
    """Entity-text count: CJK / letters / digits / punctuation; not whitespace."""
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def parse_char_quota(user_text: str) -> int | None:
    """This Turn's user text only. ASCII digits. None if the user did not name N 字."""
    text = user_text or ""
    if not text:
        return None
    preferred: list[int] = [int(m.group(1)) for m in _PREFERRED_QUOTA.finditer(text)]
    preferred.extend(int(m.group(1)) for m in _AROUND_QUOTA.finditer(text))
    if preferred:
        return max(preferred)
    fallback = [int(m.group(1)) for m in _ANY_QUOTA.finditer(text)]
    if fallback:
        return max(fallback)
    return None


def wants_outline_toc_only(user_text: str) -> bool:
    """User asked for a short TOC / title list — do not flag thin chapters."""
    text = user_text or ""
    if not text:
        return False
    if any(marker in text for marker in _TOC_MARKERS):
        return True
    probe = text.replace("短篇", "")
    return _SHORT_OUTLINE_ASK.search(probe) is not None


def outline_thin_chapters(md: str, *, min_visible: int = OUTLINE_MIN_VISIBLE) -> list[str]:
    """Titles whose body has fewer than ``min_visible`` entity chars."""
    text = md or ""
    spans: list[tuple[int, int, str]] = []
    for match in _MD_HEADING.finditer(text):
        spans.append((match.start(), match.end(), match.group(2).strip()))
    if not spans:
        for match in _CHAPTER_LINE.finditer(text):
            spans.append((match.start(), match.end(), match.group(0).strip()))
    if not spans:
        if visible_chars(text) < min_visible:
            return ["(untitled)"]
        return []
    thin: list[str] = []
    for i, (_start, end, title) in enumerate(spans):
        body_end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        if visible_chars(text[end:body_end]) < min_visible:
            thin.append(title or "(untitled)")
    return thin


def draft_length_fields(content: str, user_text: str) -> dict[str, object]:
    vis = visible_chars(content)
    out: dict[str, object] = {"visible_chars": vis}
    quota = parse_char_quota(user_text)
    if quota is None:
        return out
    out["quota_chars"] = quota
    if vis < quota * LENGTH_SHORT_RATIO:
        out["length_short"] = True
        out["summary"] = (
            f"实体文字 {vis} 字，低于约定 {quota} 字的 85%。"
            "本轮继续 draft_section 或 propose_patch 补足，不要报完工。"
        )
    return out


def outline_thin_fields(scored_md: str, user_text: str) -> dict[str, object]:
    if wants_outline_toc_only(user_text):
        return {"outline_thin": False}
    thin = outline_thin_chapters(scored_md)
    if not thin:
        return {"outline_thin": False}
    listed = "、".join(thin)
    return {
        "outline_thin": True,
        "thin_chapters": thin,
        "summary_suffix": (
            f"以下章节实体文字不足 {OUTLINE_MIN_VISIBLE} 字：{listed}。"
            "同轮加厚后再结束，不要报完工。"
        ),
    }
