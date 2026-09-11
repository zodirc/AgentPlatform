"""开篇候选灌进 volatile 的文案：书先行，轴不进必做。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from app.writing.pond_history import load_rejected_pond_groups

_FLAVOR_BIT = 48
_SELF_NOTE_BIT = 40

# 只认用户点名的长词，不认「系统」这种会误伤口令的短别名。
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


def _clip_bit(text: str, max_len: int) -> str:
    raw = (text or "").strip().replace("\n", " ")
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1] + "…"


def _book_line(item: Mapping[str, Any]) -> str:
    title = str(item.get("title") or item.get("id") or "").strip()
    flavor = _clip_bit(str(item.get("flavor") or ""), _FLAVOR_BIT)
    note = _clip_bit(str(item.get("book_self_note") or ""), _SELF_NOTE_BIT)
    bits = [f"《{title}》" if title else ""]
    if flavor:
        bits.append(flavor)
    if note:
        bits.append(f"在玩：{note}")
    return " · ".join(p for p in bits if p) or f"- {title}"


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
    """volatile：browse 不灌旧组轴；more 灌上一组每本一句话，离这几本远。"""
    from app.writing.opening_ponds import load_opening_ponds

    data = load_opening_ponds(workspace_root=workspace_root)
    if mode == "browse":
        if not data:
            return ""
        titles = "》《".join(
            str(it.get("title") or "") for it in data["items"] if it.get("title")
        )
        if not titles:
            return ""
        return f"上次给过《{titles}》；这次不必避开，但不要原样复交。"
    groups = list(load_rejected_pond_groups(workspace_root=workspace_root))
    seen_ids = {str(g.get("ponds_id") or "") for g in groups}
    if data and str(data.get("ponds_id") or "") not in seen_ids:
        groups.append(data)
    if not groups:
        return ""
    lines = [
        "## 上一组开篇候选（用户说这几本都不对）",
        "用户要的是不同的书，不是换了工位 / 证件名 / 能力名的同一本。",
        "下一组请离下面这几本远：不同的社会角落、不同的持续矛盾机制、不同的推进方式。",
        "仍在用户点名的类型里。",
    ]
    for group in groups:
        for item in group.get("items") or []:
            if isinstance(item, dict):
                lines.append(f"- {_book_line(item)}")
    return "\n".join(lines)


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    """volatile：用户只点了选择，卡片正文从 sidecar 灌给模型。不灌轴中文标签。"""
    from app.writing.opening_ponds import find_committed_pond, source_trust_label
    from app.writing.text_metrics import CHAPTER_DWELL_HINT

    item = find_committed_pond(message=message, workspace_root=workspace_root)
    if not item:
        return ""
    title = item.get("title") or item.get("id") or ""
    lines = [
        "## 已选开篇",
        "用户在卡片上勾选了一份。这是已选定的书：按「这本书」写当前章，不要再出候选。",
        "开篇只在第一章兑现，后面不要重开一次。",
        f"{CHAPTER_DWELL_HINT}。不要为凑字粘无关场面。若第二条线与本场主题对位或共享时空，可以写。",
        "按「这本书」和「开篇」写；不要另起账单、走向、气味三栏，也不要另起窗口办事。",
        f"书名：{title}",
    ]
    if item.get("flavor"):
        lines.append(f"这本书：{item['flavor']}")
    if item.get("opening"):
        lines.append(f"开篇：{item['opening']}")
    if item.get("book_self_note"):
        lines.append(f"这本书在玩什么：{item['book_self_note']}")
    trust = str(item.get("source_trust") or "")
    if trust:
        lines.append(f"力的来源：{source_trust_label(trust)}")
    if item.get("who"):
        lines.append(f"棋盘位：{item['who']}")
    if item.get("where"):
        lines.append(f"站在哪：{item['where']}")
    if item.get("want"):
        lines.append(f"入口（不是这本书要解决的事）：{item['want']}")
    return "\n".join(lines)
