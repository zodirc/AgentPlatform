"""作品尺度：短篇 / 单篇 / 长篇 —— 与卷内位置、三要素主项正交。"""

from __future__ import annotations

import re
from typing import Any, Literal

BookScope = Literal["short", "single", "long"]

_SHORT = re.compile(r"短篇|短篇小说|小小说|微型小说|闪小说")
_MEDIUM = re.compile(r"中篇|中篇小说")
_LONG = re.compile(
    r"长篇|网文|连载|修仙|玄幻|仙侠|修真|"
    r"宗门|灵根|金丹|元婴|练气|功法|秘境|妖兽|"
    r"升级|爽文|系统流|穿越|重生"
)
_STANDALONE = re.compile(
    r"写一篇|写个故事|写一个故事|另写一篇|写篇(?:新的)?故事"
)
_MID_BOOK = re.compile(
    r"续写|接着写|继续写|往下写|下一章|下章|"
    r"第\s*[二三四五六七八九十百千零〇两\d]{1,4}\s*章|"
    r"(?:^|\b)ch([2-9]|\d{2,})\b",
    re.I,
)

_SCOPE_LABELS = {
    "short": "短篇",
    "single": "单篇",
    "long": "长篇",
}

DEFAULT_SHORT_MIN = 1500
DEFAULT_SHORT_TARGET = 2500
DEFAULT_SINGLE_MIN = 2500
DEFAULT_SINGLE_TARGET = 3500


def normalize_book_scope(value: str | None) -> BookScope:
    token = (value or "").strip().lower()
    if token in {"short", "single", "long"}:
        return token  # type: ignore[return-value]
    return "single"


def book_scope_label(scope: str) -> str:
    return _SCOPE_LABELS.get(normalize_book_scope(scope), scope)


def infer_book_scope(
    message: str = "",
    *,
    outline: str = "",
    section_id: str = "",
    manuscript_chapters: int = 0,
) -> BookScope:
    """推断作品尺度（与 chapter 位置独立）。"""
    blob = "\n".join(x for x in (message, outline) if x).strip()
    sid = (section_id or "").strip().lower()
    n = manuscript_chapters

    if _SHORT.search(blob):
        return "short"
    if _MEDIUM.search(blob):
        return "single"
    if _LONG.search(blob):
        return "long"
    if _MID_BOOK.search(blob) or _MID_BOOK.search(sid):
        return "long"
    m = re.match(r"^ch(\d+)$", sid)
    if m and int(m.group(1)) >= 2:
        return "long"
    if n >= 2:
        return "long"
    if outline.strip():
        from app.writing.outline_arc import _chapter_spans, _LONG_FORM

        if _LONG_FORM.search(blob) or len(_chapter_spans(outline)) >= 4:
            return "long"
    if _STANDALONE.search(blob) and not _LONG.search(blob):
        return "single"
    return "single"


def default_draft_quota_for_scope(scope: str, user_text: str = "") -> int | None:
    """尺度默认正文字数（点名 N 字由 parse_char_quota 优先）。"""
    from app.writing.text_metrics import (
        DEFAULT_CHAPTER_MIN,
        looks_like_chapter_draft,
        parse_char_quota,
        wants_short_prose,
    )

    if wants_short_prose(user_text):
        return None
    named = parse_char_quota(user_text)
    if named is not None:
        return named
    sc = normalize_book_scope(scope)
    if sc == "short":
        if _SHORT.search(user_text or "") or _STANDALONE.search(user_text or ""):
            return DEFAULT_SHORT_TARGET
        return None
    if sc == "single":
        if _STANDALONE.search(user_text or ""):
            return DEFAULT_SINGLE_TARGET
        return None
    if looks_like_chapter_draft(user_text):
        return DEFAULT_CHAPTER_MIN
    return None


def scope_spec_line(scope: str, *, position: str = "", section_num: int | None = None) -> str:
    """Writing spec 尺度行。"""
    sc = normalize_book_scope(scope)
    pos = (position or "").strip().lower()
    if sc == "short":
        return (
            "短篇：整篇微型弧（开端→发展→高潮→结局）；"
            "三要素压缩交织，环境窄而深，一篇收束；不用长篇开篇三章契约"
        )
    if sc == "single":
        return (
            "单篇：一篇完整小故事；三要素同屏推进，环境先可站，人物与情节同步；"
            "不必分章交代设定"
        )
    if pos == "climax":
        return (
            "长篇·高潮：情节顶满一件主线麻烦；人物极限处做选择；"
            "环境收紧同场，勿重播世界观"
        )
    if pos == "falling":
        return "长篇·收束：落下/余波/代价落地；不新开大线，勿假高潮"
    if pos == "turn":
        return "长篇·翻转：中段变向；仍只推一个主项，扣 spine"
    if section_num is not None and section_num <= 3:
        return "长篇·开篇窗口：按 outline 前三章契约（ch1 环境 · ch2 世界再推 · ch3 人物/麻烦）"
    if section_num is not None and section_num >= 4:
        return (
            "长篇·中段：breadth=spine+outline map；detail=prev tail+本章 job；"
            "环境只写增量，勿重播开篇已交代的世界质地"
        )
    return "长篇：先 outline（含 spine），再按章 job 写；每章一个三要素主项"


def default_duty_for_scope(
    scope: str,
    *,
    work_mode: str,
    position: str = "",
    chapter_kind: str | None = None,
) -> str:
    """无 outline 时的默认章职。"""
    from app.writing.work_mode import default_opening_duty, normalize_work_mode

    sc = normalize_book_scope(scope)
    pos = (position or "").strip().lower()
    mode = normalize_work_mode(work_mode)
    kind = (chapter_kind or "").strip().lower()

    if sc == "short":
        return (
            "短篇·微型弧：环境窄深先可站，人物与麻烦同步显现，"
            "一篇内推到小高潮并落下；禁止卷纲浓缩与设定百科"
        )
    if sc == "single":
        return (
            "单篇·完整弧：三要素交织，环境托举，人物从选择上显露，"
            "情节只推一两步但有落点；句味/类型化按 work_mode"
        )
    if pos == "climax":
        return "高潮章：一件主线麻烦顶满；副线只碰撞主线；人物选择可见"
    if pos == "falling":
        return "收束章：余波与代价；关系/局面落下，不新开卷级冲突"
    if pos in {"opening", "rising", "turn"} and sc == "long":
        if pos == "opening" or (kind and kind != "plot_step"):
            return default_opening_duty(mode, chapter_kind=chapter_kind or "world_rule")
        return "加压/台阶：在已立规矩下推进一步；人物仍在场上"
    return default_opening_duty(mode, chapter_kind=chapter_kind or "world_rule")


def resolve_book_scope_context(
    message: str = "",
    *,
    outline: str = "",
    section_id: str = "",
    manuscript_chapters: int = 0,
    position: str = "",
) -> dict[str, Any]:
    scope = infer_book_scope(
        message,
        outline=outline,
        section_id=section_id,
        manuscript_chapters=manuscript_chapters,
    )
    sid = (section_id or "").strip().lower()
    m = re.match(r"^ch(\d+)$", sid)
    section_num = int(m.group(1)) if m else None
    return {
        "book_scope": scope,
        "book_scope_label": book_scope_label(scope),
        "section_num": section_num,
        "scope_spec_line": scope_spec_line(
            scope, position=position, section_num=section_num
        ),
    }
