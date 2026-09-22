"""开篇候选灌进 volatile 的文案：书先行，轴不进必做。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

_USER_KIND_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "granted_path",
        ("金手指流", "金手指落到", "系统/金手指", "开启系统", "金手指"),
    ),
    ("self_notice", ("自己发觉能变强", "自己变强", "自己发觉")),
    ("pulled_in", ("被卷进已在运转", "被卷进")),
    (
        "world_already",
        ("超凡已是这城的日常", "异能已经混在人群里", "超凡已是日常"),
    ),
    ("no_extraordinary", ("先过日子", "先过班房租", "凡人流")),
)
_USER_AXIS_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lifespan", ("用寿或命结账", "烧寿", "扣寿")),
    ("memory", ("用记忆结账", "记忆税")),
    ("contract", ("用契或名册结账",)),
    ("status", ("用名分或籍结账",)),
    ("none", ("不当场拿命或记忆结账",)),
)


def format_user_axis_intent_block(message: str) -> str:
    """用户明确点名轴时，把它写成用户约束，而不是 harness 造差异。"""
    from app.writing.opening_ponds import PRICE_AXIS_LABELS, START_KIND_LABELS

    text = message or ""
    if not text.strip():
        return ""
    hits: list[str] = []
    seen: set[str] = set()
    for token, phrases in _USER_KIND_PHRASES:
        if token in seen:
            continue
        if any(p in text for p in phrases):
            seen.add(token)
            hits.append(START_KIND_LABELS.get(token, token))
    for token, phrases in _USER_AXIS_PHRASES:
        key = f"axis:{token}"
        if key in seen:
            continue
        if any(p in text for p in phrases):
            seen.add(key)
            hits.append(PRICE_AXIS_LABELS.get(token, token))
    if not hits:
        return ""
    named = "、".join(hits)
    return (
        "## 用户点名的轴\n"
        f"用户点名：{named}。这是用户约束，不是要你按标签造书。"
    )


def format_opening_ponds_block(
    *,
    workspace_root: Path | None = None,
    mode: Literal["more", "browse"] = "browse",
) -> str:
    """历史候选只留 sidecar / pond_history，给 similarity 闸门用，不进模型。"""
    del workspace_root, mode
    return ""


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    """volatile：用户只点了选择，卡片正文从 sidecar 灌给模型。不灌轴中文标签。"""
    from app.writing.opening_ponds import find_committed_pond
    from app.writing.text_metrics import CHAPTER_DWELL_HINT

    item = find_committed_pond(message=message, workspace_root=workspace_root)
    if not item:
        return ""
    title = item.get("title") or item.get("id") or ""
    lines = [
        "## 已选作品",
        "用户在卡片上勾选了一本。下面是这本书的简介，不是正文。"
        "先把大纲写入 outline.md，写完停。主线写人怎么变；近处这一章两三句章职，远处一句备忘。"
        "开篇就是将来章首，不要把简介原样贴进稿。",
        f"{CHAPTER_DWELL_HINT}。不要为凑字粘无关场面。若第二条线与本场主题对位或共享时空，可以写。",
        "按这本书写；不要另起账单、走向、气味三栏，也不要另起窗口办事。",
        f"书名：{title}",
    ]
    if item.get("flavor"):
        lines.append(f"这本书：{item['flavor']}")
    if item.get("opening"):
        lines.append(f"简介：{item['opening']}")
    return "\n".join(lines)
