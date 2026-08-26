"""章位置 × 章类型：在作品风格之下收窄本章怎么写。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from app.writing.work_mode import normalize_work_mode

ChapterPosition = Literal["opening", "rising", "turn", "climax", "falling"]
ChapterKind = Literal[
    "live_character",
    "plot_step",
    "world_rule",
    "conflict_hook",
    "climax_payoff",
]

CHAPTER_POSITIONS: tuple[str, ...] = (
    "opening",
    "rising",
    "turn",
    "climax",
    "falling",
)
CHAPTER_KINDS: tuple[str, ...] = (
    "live_character",
    "plot_step",
    "world_rule",
    "conflict_hook",
    "climax_payoff",
)

_POSITION_LABELS = {
    "opening": "开篇",
    "rising": "铺垫/加压中段",
    "turn": "翻转",
    "climax": "高潮落点",
    "falling": "落下/收束",
}

_KIND_LABELS = {
    "live_character": "立人过日子",
    "plot_step": "情节台阶",
    "world_rule": "环境/规则",
    "conflict_hook": "冲突强钩",
    "climax_payoff": "高潮兑现",
}

_OPENING = re.compile(
    r"第一章|开篇|开场|第\s*1\s*章|(?:^|\b)ch1\b|写一章.*第一"
)
_CLIMAX_POS = re.compile(r"高潮章|摊牌章|决战|卷末|本卷顶点|第\s*[六七八九十\d]+\s*章.*高潮")
_TURN = re.compile(r"翻转|中段高潮|半程|中盘")
_FALLING = re.compile(r"收束|落下|尾声|余波|终章")

_KIND_LIVE = re.compile(r"立人|过日子|认识.*人|人物为主|日常立住|生活感")
_KIND_HOOK = re.compile(r"强钩|异变|开局冲突|直接开打|悬念开篇")
_KIND_PLOT = re.compile(r"情节|推进|台阶|追索|加压")
_KIND_WORLD = re.compile(r"环境|世界观|规矩|设定|质地")
_KIND_PAYOFF = re.compile(r"高潮|摊牌|决战|兑现|到顶")

_SECTION_NUM = re.compile(r"^(?:ch|chapter)?0*([0-9]+)$", re.I)
_OUTLINE_MAIN_ITEM = re.compile(r"主项[：:]\s*(环境|人物|情节|规则)")


def infer_chapter_kind_from_duty(duty: str) -> ChapterKind | None:
    """outline 章纲「主项：环境/人物/情节」→ 章类型。"""
    m = _OUTLINE_MAIN_ITEM.search(duty or "")
    if m:
        token = m.group(1)
        if token in {"环境", "规则"}:
            return "world_rule"
        if token == "人物":
            return "live_character"
        return "plot_step"
    if _KIND_WORLD.search(duty or "") and not _KIND_PLOT.search(duty or ""):
        return "world_rule"
    return None


def normalize_chapter_position(value: str | None) -> ChapterPosition:
    token = (value or "").strip().lower()
    if token in CHAPTER_POSITIONS:
        return token  # type: ignore[return-value]
    return "rising"


def normalize_chapter_kind(value: str | None) -> ChapterKind:
    token = (value or "").strip().lower()
    if token in CHAPTER_KINDS:
        return token  # type: ignore[return-value]
    return "live_character"


def chapter_position_label(pos: str) -> str:
    return _POSITION_LABELS.get(normalize_chapter_position(pos), pos)


def chapter_kind_label(kind: str) -> str:
    return _KIND_LABELS.get(normalize_chapter_kind(kind), kind)


def _section_number(section_id: str) -> int | None:
    sid = (section_id or "").strip()
    m = _SECTION_NUM.match(sid)
    if m:
        return int(m.group(1))
    return None


def infer_chapter_position(
    *,
    section_id: str = "",
    message: str = "",
    duty: str = "",
    book_scope: str = "single",
) -> ChapterPosition:
    from app.writing.book_scope import normalize_book_scope

    scope = normalize_book_scope(book_scope)
    blob = f"{section_id}\n{message}\n{duty}"
    n = _section_number(section_id)
    if n == 1 and scope == "long":
        return "opening"
    if _CLIMAX_POS.search(blob) or _KIND_PAYOFF.search(duty):
        return "climax"
    if n is None or n > 3:
        if _FALLING.search(blob):
            return "falling"
    if _TURN.search(blob):
        return "turn"
    if n is not None and n >= 2:
        return "rising"
    if _OPENING.search(message) or _OPENING.search(duty):
        return "opening" if scope == "long" else "rising"
    if not section_id and _OPENING.search(blob):
        return "opening" if scope == "long" else "rising"
    if (
        not section_id
        and scope in {"short", "single"}
        and re.search(r"写一篇|写一章|写个故事", message or "")
    ):
        return "rising"
    return "rising"


def infer_chapter_kind(
    *,
    position: str,
    work_mode: str,
    message: str = "",
    duty: str = "",
    book_scope: str = "single",
) -> ChapterKind:
    from app.writing.book_scope import normalize_book_scope

    scope = normalize_book_scope(book_scope)
    blob = f"{message}\n{duty}"
    if _KIND_PAYOFF.search(blob) or normalize_chapter_position(position) == "climax":
        return "climax_payoff"
    if _KIND_HOOK.search(blob):
        return "conflict_hook"
    if _KIND_LIVE.search(blob):
        return "live_character"
    if _KIND_WORLD.search(blob) and not _KIND_PLOT.search(blob):
        return "world_rule"
    if _KIND_PLOT.search(blob):
        return "plot_step"

    pos = normalize_chapter_position(position)
    mode = normalize_work_mode(work_mode)
    if scope in {"short", "single"} and pos in {"opening", "rising", "turn"}:
        if _KIND_PLOT.search(blob) and not _KIND_WORLD.search(blob):
            return "plot_step"
        return "live_character"
    if pos == "opening" and scope == "long":
        if mode == "web_serial":
            return "world_rule"
        return "world_rule"
    if pos == "climax":
        return "climax_payoff"
    if pos == "falling":
        return "live_character"
    if mode == "web_serial":
        return "plot_step"
    return "live_character"


def chapter_kind_to_fragment(kind: str) -> str:
    mapping = {
        "live_character": "dialogue_dyad",
        "plot_step": "plot_progress",
        "world_rule": "worldview_texture",
        "conflict_hook": "plot_progress",
        "climax_payoff": "climax_beat",
    }
    return mapping.get(normalize_chapter_kind(kind), "mixed")


def chapter_kind_obligation(
    kind: str, *, work_mode: str, position: str, book_scope: str = "single"
) -> str:
    k = normalize_chapter_kind(kind)
    pos = normalize_chapter_position(position)
    mode = normalize_work_mode(work_mode)
    from app.writing.book_scope import default_duty_for_scope, normalize_book_scope

    scope = normalize_book_scope(book_scope)
    if scope in {"short", "single"}:
        return default_duty_for_scope(
            scope, work_mode=mode, position=pos, chapter_kind=k
        )
    if k == "live_character":
        if pos == "opening":
            return (
                "本章立人：让读者认识这个人怎么过日子/相处；"
                "少事、多在场。禁止把气氛/悬念/伏笔/世界观/主线一次灌满（卷纲浓缩）。"
                + (
                    "可留一丝第一阶信息差，但人物先立住。"
                    if mode == "web_serial"
                    else "句味与人物距离优先。"
                )
            )
        return "本章立人：人物选择与关系在场上，勿空转设定演讲"
    if k == "world_rule":
        if pos == "opening" and scope == "long":
            return (
                "本章环境/规则：社会背景与自然场景先可站；"
                "写清何时何地、什么规矩在管事、什么物件/稀缺在制约人。"
                + (
                    " ch2 再推世界质地或悬念台阶（不必写「能/不能做什么」手册）；"
                    "本章只锚定可站之处与一条生活规矩。"
                    if mode == "web_serial"
                    else " 机构专名勿当第一词；身世不要提要。"
                )
            )
        if pos in {"rising", "turn"} and scope == "long":
            return "本章环境/规则：只写**增量**（新地点/新规矩/新代价），勿重播已立设定"
        return "本章环境/规则：规矩可感可用，托住人物，勿开场背设定"
    if k == "conflict_hook":
        return (
            "本章强钩：冲突/异变可先顶，但仍要有人；"
            "只兑第一阶悬念，禁止卷末大高潮与设定百科"
        )
    if k == "plot_step":
        return "本章情节台阶：新信息/对手/代价之一可见；人物仍在场上做选择"
    if k == "climax_payoff":
        return "本章高潮兑现：一件主线麻烦顶满；副线只碰撞主线"
    return ""


def resolve_chapter_role(
    *,
    section_id: str = "",
    message: str = "",
    duty: str = "",
    work_mode: str = "literary",
    workspace_root: Path | None = None,
    book_scope: str | None = None,
    outline: str = "",
    manuscript_chapters: int = 0,
) -> dict[str, Any]:
    """综合尺度 + 位置 + 用户句 + outline 主项 → 章类型。"""
    from app.writing.book_scope import infer_book_scope

    scope = book_scope or infer_book_scope(
        message,
        outline=outline,
        section_id=section_id,
        manuscript_chapters=manuscript_chapters,
    )
    position = infer_chapter_position(
        section_id=section_id,
        message=message,
        duty=duty,
        book_scope=scope,
    )
    kind_override = infer_chapter_kind_from_duty(duty)
    kind = kind_override or infer_chapter_kind(
        position=position,
        work_mode=work_mode,
        message=message,
        duty=duty,
        book_scope=scope,
    )
    return {
        "book_scope": scope,
        "chapter_position": position,
        "chapter_position_label": chapter_position_label(position),
        "chapter_kind": kind,
        "chapter_kind_label": chapter_kind_label(kind),
        "preferred_fragment": chapter_kind_to_fragment(kind),
        "obligation": chapter_kind_obligation(
            kind, work_mode=work_mode, position=position, book_scope=scope
        ),
    }

