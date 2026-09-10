"""作品尺度：短篇 / 单篇 / 长篇 —— 与卷内位置、三要素主项正交。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

BookScope = Literal["short", "single", "long"]
BookScopeSource = Literal["auto", "user"]

_SHORT = re.compile(r"短篇|短篇小说|小小说|微型小说|闪小说")
_MEDIUM = re.compile(r"中篇|中篇小说")
# 尺度词：明确要写长、写章、连载。题材词（玄幻/修仙）不单独把「一篇」抬成长篇。
_EXPLICIT_LONG_SCALE = re.compile(r"长篇|网文|连载|写一章|写个章|写一回")
_CHAPTER_REF = re.compile(
    r"第\s*[一二三四五六七八九十百千零〇两\d]+\s*章"
)
_GENRE_LONG = re.compile(
    r"修仙|玄幻|仙侠|修真|"
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


def explicit_book_scope(message: str = "") -> BookScope | None:
    """句里写明的尺度。短篇/长篇/写一章优先于 prefs 钉死；「写一篇」和「第 N 章」不算。"""
    blob = (message or "").strip()
    if not blob:
        return None
    if _SHORT.search(blob):
        return "short"
    if _MEDIUM.search(blob):
        return "single"
    if _EXPLICIT_LONG_SCALE.search(blob):
        return "long"
    return None


def load_book_scope_override(
    *,
    workspace_root: Path | None = None,
) -> dict[str, Any] | None:
    """从 writing_prefs.json 读 book_scope 钉死态。"""
    from app.writing.work_mode import load_writing_prefs

    data = load_writing_prefs(workspace_root=workspace_root)
    raw = data.get("book_scope")
    if isinstance(raw, dict):
        source = str(raw.get("source") or "auto").strip().lower()
        if source not in {"auto", "user"}:
            source = "auto"
        token = raw.get("scope") or raw.get("mode")
        return {"scope": normalize_book_scope(str(token or "")), "source": source}
    return None


def save_book_scope_override(
    *,
    scope: str | None = None,
    source: BookScopeSource = "user",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """更新 prefs 中的 book_scope；保留 work_mode / style_gains。"""
    from app.writing.work_mode import load_writing_prefs, save_writing_prefs

    data = load_writing_prefs(workspace_root=workspace_root)
    data["book_scope"] = {
        "source": source,
        "scope": normalize_book_scope(scope),
    }
    return save_writing_prefs(data, workspace_root=workspace_root)


def resolve_book_scope(
    message: str = "",
    *,
    outline: str = "",
    section_id: str = "",
    manuscript_chapters: int = 0,
    workspace_root: Path | None = None,
    override: str | None = None,
) -> tuple[BookScope, BookScopeSource]:
    """显式尺度词 > 用户钉死 > 推断。"""
    if override is not None and str(override).strip():
        return normalize_book_scope(override), "user"
    named = explicit_book_scope(message)
    if named is not None:
        return named, "auto"
    stored = load_book_scope_override(workspace_root=workspace_root)
    if stored and stored.get("source") == "user":
        return normalize_book_scope(str(stored.get("scope"))), "user"
    return (
        infer_book_scope(
            message,
            outline=outline,
            section_id=section_id,
            manuscript_chapters=manuscript_chapters,
        ),
        "auto",
    )


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
    # 「写一篇」优先于题材词和「第 N 章」：带题材的完篇仍是单篇。
    if _STANDALONE.search(blob) and not _EXPLICIT_LONG_SCALE.search(blob):
        return "single"
    if _EXPLICIT_LONG_SCALE.search(blob) or _GENRE_LONG.search(blob):
        return "long"
    if _CHAPTER_REF.search(blob) or _MID_BOOK.search(blob) or _MID_BOOK.search(sid):
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


def scope_spec_line(
    scope: str,
    *,
    position: str = "",
    section_num: int | None = None,
    work_mode: str = "",
    message: str = "",
    outline: str = "",
) -> str:
    """Writing spec 尺度行。"""
    sc = normalize_book_scope(scope)
    pos = (position or "").strip().lower()
    if pos == "climax":
        prefix = "长篇·" if sc == "long" else ""
        return (
            f"{prefix}这场偏高潮：一件麻烦顶住即可；"
            "勿重播设定，句子可紧可短"
        )
    if sc == "short":
        return (
            "短篇：一篇收束的微型弧；人、事、地交织，环境窄而深；"
            "不必订长篇纲，也不必套开篇工序"
        )
    if sc == "single":
        return (
            "单篇：一篇完整小故事，本 Turn 可交卷；人、事、地同场即可；"
            "不必分章、不必订长篇纲"
        )
    if pos == "falling":
        return "长篇·收束：余波与局面落地；不新开无关大线。主题对位的副线可以收"
    if pos == "turn":
        return "长篇·翻转：中段可以变向；扣已有线索写这场"
    if section_num is not None and section_num <= 3:
        from app.writing.work_mode import normalize_work_mode

        if normalize_work_mode(work_mode) == "web_serial":
            from app.writing.outline_phase import wants_opening_candidates
            from app.writing.work_mode import serial_opening_compass

            if wants_opening_candidates(message, outline=outline):
                return (
                    "长篇·开写：propose_opening_ponds 出开篇候选；"
                    "start_kind 不得重复（发觉/系统/过日子），promise 不得全员相同"
                )
            compass = serial_opening_compass(message=message, outline=outline)
            return (
                f"长篇·开篇：{compass}；一章通常一场，长篇约一千八到四千五；"
                "不要为凑字粘无关场面；第二条线若与本场主题对位或共享时空，可以写；"
                "后面的海（终局宇宙、境界总纲）不要写进这一章"
            )
        return (
            "长篇·开篇：站住眼前的日子和人；一章通常一场，长篇约一千八到四千五；"
            "不要为凑字粘无关场面；第二条线若与本场主题对位或共享时空，可以写；"
            "后面的海（终局宇宙、境界总纲）不要写进这一章"
        )
    if section_num is not None and section_num >= 4:
        return (
            "长篇·中段：扣已有线索写这场；换地图或抬压强即可，勿重播开篇"
        )
    return "长篇：有纲跟这场的章职写；本 Turn 只交一章，不是把全书写完"


def default_duty_for_scope(
    scope: str,
    *,
    work_mode: str,
    position: str = "",
    chapter_kind: str | None = None,
    message: str = "",
    outline: str = "",
) -> str:
    """无 outline 时的默认章职。"""
    from app.writing.work_mode import default_opening_duty, normalize_work_mode

    sc = normalize_book_scope(scope)
    pos = (position or "").strip().lower()
    mode = normalize_work_mode(work_mode)
    kind = (chapter_kind or "").strip().lower()

    if sc == "short":
        return (
            "短篇倾向：人、事、地交织，环境窄而深，一篇内可有起落；"
            "开篇只兑这一场，不必另起长篇契约"
        )
    if sc == "single":
        return (
            "单篇倾向：三要素同场即可；句味/类型化按 work_mode；"
            "本篇收束，不必按环境→人物→情节交卷"
        )
    if pos == "climax":
        return "高潮章：一件主线麻烦顶满；副线只碰撞主线；人物选择可见"
    if pos == "falling":
        return "收束章：余波与局面落下，不新开卷级冲突"
    if pos in {"opening", "rising", "turn"} and sc == "long":
        if pos == "opening" or (kind and kind != "plot_step"):
            return default_opening_duty(
                mode,
                chapter_kind=chapter_kind or "live_character",
                message=message,
                outline=outline,
            )
        return "加压/台阶：在已立的日子里推进一步；人物仍在场上"
    return default_opening_duty(
        mode,
        chapter_kind=chapter_kind or "live_character",
        message=message,
        outline=outline,
    )


def resolve_book_scope_context(
    message: str = "",
    *,
    outline: str = "",
    section_id: str = "",
    manuscript_chapters: int = 0,
    position: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    scope, _src = resolve_book_scope(
        message,
        outline=outline,
        section_id=section_id,
        manuscript_chapters=manuscript_chapters,
        workspace_root=workspace_root,
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
