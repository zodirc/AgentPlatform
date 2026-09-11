"""长度/大纲薄度事实；N字=实体文字。"""

from __future__ import annotations

import re

LENGTH_SHORT_RATIO = 0.85
OUTLINE_MIN_VISIBLE = 40
# 长篇默认区间 1800–4500。无名额时 length_short 只在 <1500 记。
DEFAULT_CHAPTER_MIN = 1800
DEFAULT_CHAPTER_MAX = 4500
LENGTH_SHORT_FLOOR = 1500
CHAPTER_DWELL_HINT = (
    "一章通常一场，长篇约一千八到四千五；两场并置或半场留到下章都可以。"
    "不要预告片再粘无关的下一场。第二条线若与本场主题对位或共享时空，可以写"
)

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

# Surgical / explicitly short prose — do not apply the chapter default.
_SHORT_PROSE_ASK = re.compile(
    r"改一句|改短|补一句|只要这句|润色这|"
    r"(?:写|改)短(?!篇)|"
    r"短(?:一点|一些|点)|"
    r"简略"
)

_CHAPTER_DRAFT_ASK = re.compile(
    r"成篇|一篇|一章|本章|这一章|扩写|续写|"
    r"采用此开篇|按此开篇|按开篇候选|"
    r"写第|[第][一二三四五六七八九十百千零〇两\d]+章"
)

_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.M)
_CHAPTER_LINE = re.compile(
    r"^第[一二三四五六七八九十百千零〇两\d]+章\b.*$",
    re.M,
)


def visible_chars(text: str) -> int:
    """实体字计数。
    
    参数:
        text。
    
    返回:
        int。"""
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def clip_visible(text: str, max_chars: int, *, ellipsis: bool = False) -> str:
    """截到至多 max_chars 个实体字；空白仍保留到截断点。"""
    body = text or ""
    cap = max(0, int(max_chars))
    if cap <= 0:
        return ""
    if visible_chars(body) <= cap:
        return body
    budget = cap - 1 if ellipsis else cap
    if budget <= 0:
        return "…" if ellipsis else ""
    clipped: list[str] = []
    n = 0
    for ch in body:
        if not ch.isspace():
            n += 1
        clipped.append(ch)
        if n >= budget:
            break
    out = "".join(clipped).rstrip()
    if ellipsis:
        return out + "…"
    return out


def parse_char_quota(user_text: str) -> int | None:
    """解析 N 字配额。
    
    参数:
        user_text。
    
    返回:
        int|None。"""
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


def wants_short_prose(user_text: str) -> bool:
    """是否短 prose。
    
    参数:
        user_text。
    
    返回:
        bool。"""
    text = user_text or ""
    if not text.strip():
        return False
    probe = text.replace("短篇", "")
    return _SHORT_PROSE_ASK.search(probe) is not None


def looks_like_chapter_draft(user_text: str) -> bool:
    """是否章 draft。
    
    参数:
        user_text。
    
    返回:
        bool。"""
    text = user_text or ""
    if not text.strip() or wants_short_prose(text):
        return False
    return _CHAPTER_DRAFT_ASK.search(text) is not None


def resolve_draft_quota(user_text: str, *, book_scope: str | None = None) -> int | None:
    """draft 配额（尺度感知）。"""
    from app.writing.book_scope import default_draft_quota_for_scope, resolve_book_scope

    named = parse_char_quota(user_text)
    if named is not None:
        return named
    if book_scope:
        from app.writing.book_scope import normalize_book_scope

        scope = normalize_book_scope(book_scope)
    else:
        scope, _src = resolve_book_scope(user_text)
    scoped = default_draft_quota_for_scope(scope, user_text)
    if scoped is not None:
        return scoped
    if looks_like_chapter_draft(user_text):
        return DEFAULT_CHAPTER_MIN
    return None


def wants_outline_toc_only(user_text: str) -> bool:
    """是否短目录。
    
    参数:
        user_text。
    
    返回:
        bool。"""
    text = user_text or ""
    if not text:
        return False
    if any(marker in text for marker in _TOC_MARKERS):
        return True
    probe = text.replace("短篇", "")
    return _SHORT_OUTLINE_ASK.search(probe) is not None


def outline_thin_chapters(md: str, *, min_visible: int = OUTLINE_MIN_VISIBLE) -> list[str]:
    """偏薄章标题。
    
    参数:
        md/min_visible。
    
    返回:
        list。"""
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
    """长度软事实。无名额：<1500 才记 length_short；点名配额仍用 85%。"""
    vis = visible_chars(content)
    out: dict[str, object] = {"visible_chars": vis}
    named = parse_char_quota(user_text)
    if named is not None:
        out["quota_chars"] = named
        if vis < named * LENGTH_SHORT_RATIO:
            out["length_short"] = True
            out["summary"] = length_short_summary(vis, named)
        return out
    quota = resolve_draft_quota(user_text)
    if quota is None:
        if looks_like_chapter_draft(user_text) and vis < LENGTH_SHORT_FLOOR:
            out["quota_min"] = DEFAULT_CHAPTER_MIN
            out["quota_max"] = DEFAULT_CHAPTER_MAX
            out["length_short"] = True
            out["summary"] = length_short_summary(vis, LENGTH_SHORT_FLOOR)
        return out
    out["quota_chars"] = quota
    out["quota_min"] = DEFAULT_CHAPTER_MIN
    out["quota_max"] = DEFAULT_CHAPTER_MAX
    # 默认章配额不再用 85% 点值；只在低于地板时记。
    if looks_like_chapter_draft(user_text) and named is None:
        if vis < LENGTH_SHORT_FLOOR:
            out["length_short"] = True
            out["summary"] = length_short_summary(vis, LENGTH_SHORT_FLOOR)
        return out
    if vis < quota * LENGTH_SHORT_RATIO:
        out["length_short"] = True
        out["summary"] = length_short_summary(vis, quota)
    return out


def length_short_summary(vis: int, quota: int) -> str:
    """篇幅不足时的提示：只说现在多短。"""
    return (
        f"实体文字 {vis} 字，低于门槛 {quota} 字"
        f"（长篇区间 {DEFAULT_CHAPTER_MIN}–{DEFAULT_CHAPTER_MAX}）。"
        "若这场已经收住，下一站留给下一章。"
    )


def outline_thin_fields(scored_md: str, user_text: str) -> dict[str, object]:
    """大纲薄软事实。
    
    参数:
        scored_md/user_text。
    
    返回:
        dict。"""
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
            f"以下章节标题下几乎没有这场要干什么：{listed}。"
            "点明即可，不必写成小正文。"
        ),
    }
