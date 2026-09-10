"""长度/大纲薄度事实；N字=实体文字。"""

from __future__ import annotations

import re

LENGTH_SHORT_RATIO = 0.85
OUTLINE_MIN_VISIBLE = 40
# 起点常章：配额 3000，软顶 3500。不足 85%（2550）记 length_short。
DEFAULT_CHAPTER_MIN = 3000
DEFAULT_CHAPTER_MAX = 3500
CHAPTER_DWELL_HINT = (
    "一章一场，按起点习惯约三千字写满（对白、拆拍、反应），软顶三千五；"
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
    """长度软事实。
    
    参数:
        content/user_text。
    
    返回:
        dict。"""
    vis = visible_chars(content)
    out: dict[str, object] = {"visible_chars": vis}
    quota = resolve_draft_quota(user_text)
    if quota is None:
        return out
    out["quota_chars"] = quota
    if vis < quota * LENGTH_SHORT_RATIO:
        out["length_short"] = True
        out["summary"] = length_short_summary(vis, quota)
    return out


def length_short_summary(vis: int, quota: int) -> str:
    """篇幅不足时的提示：写满已有拍，不要 append 第二场。"""
    return (
        f"实体文字 {vis} 字，低于约定 {quota} 字的 85%"
        f"（软顶 {DEFAULT_CHAPTER_MAX}）。"
        "在已有拍里写满对白、拆拍、反应；不要新出场、新地点、新反派。"
        "若这场已经收住，下一站留给下一章，不要 mode=append 粘第二场。"
        "不要报完工。"
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
