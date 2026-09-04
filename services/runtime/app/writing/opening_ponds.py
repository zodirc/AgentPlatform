"""开篇近池候选：结构化交卷，供聊天内点选（像 Plan 清单）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

OPENING_PONDS_REL = Path(".agent") / "work" / "opening_ponds.json"
MORE_PONDS_MESSAGE = (
    "这几个都不合适。再给 2～3 个互不换皮的开篇候选"
    "（跟着谁、站在哪、眼下要什么、超凡怎么开始都要换）。"
    "至少一份是主角在有人的日子里自己发觉能做什么，"
    "不要三份都是开窗死人、灵异出事、城市异变。"
)
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_opening_ponds", "stub_echo"})
_OPENING_CHOICE_BLOCK = """## Opening choice (platform)
This turn is a Plan-like picker. Call `propose_opening_ponds` once with 2–3 items
(title, who, where, want, chapter_job). The UI card is the deliverable.
Do not list the three ponds in the assistant message. Do not call draft_section
or update_outline. One short sentence is enough: ask the user to pick a card
or say 我要其他的.

Ponds must differ in how the extraordinary starts, not just job and district.
At least one pond: the protagonist notices a capability or bodily change in
themselves on an ordinary day with other people around. Do not submit three
urban-occult incidents (window-death, haunting, city glitch, corpse, haunted
object) in different workplaces — that is the same pond in new coats.
"""


def opening_choice_block() -> str:
    """volatile：开篇点选纪律（不焊进 system 前缀）。"""
    return _OPENING_CHOICE_BLOCK.strip()


def should_gate_opening_choice(
    message: str,
    *,
    outline: str | None = None,
    tool_names: list[str] | tuple[str, ...] | None = None,
    workspace_root: Path | None = None,
) -> bool:
    """Profile 有开篇工具、且本轮只要候选时，闸成只剩 propose_opening_ponds。"""
    if tool_names is not None and "propose_opening_ponds" not in tool_names:
        return False
    text = outline
    if text is None:
        path = _workspace(workspace_root) / "outline.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        else:
            text = ""
    from app.writing.outline_phase import wants_opening_candidates

    return wants_opening_candidates(message, outline=text)

_TITLE_MAX = 80
_FIELD_MAX = 240
_SUMMARY_MAX = 160
_MIN_ITEMS = 2
_MAX_ITEMS = 4


def _workspace(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def opening_ponds_path(workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / OPENING_PONDS_REL


def _clip(value: Any, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def normalize_pond_item(raw: dict[str, Any], index: int) -> dict[str, str]:
    """一条近池：标题 + 跟着谁 / 站在哪 / 眼下要什么 / 这一章。"""
    title = _clip(raw.get("title") or raw.get("name") or f"候选 {index + 1}", _TITLE_MAX)
    item_id = _clip(raw.get("id") or f"pond-{index + 1}", 32) or f"pond-{index + 1}"
    return {
        "id": item_id,
        "title": title or f"候选 {index + 1}",
        "who": _clip(raw.get("who") or raw.get("跟着谁") or "", _FIELD_MAX),
        "where": _clip(raw.get("where") or raw.get("站在哪") or "", _FIELD_MAX),
        "want": _clip(raw.get("want") or raw.get("眼下要什么") or "", _FIELD_MAX),
        "chapter_job": _clip(
            raw.get("chapter_job") or raw.get("这一章干什么") or "", _FIELD_MAX
        ),
        "summary": _clip(raw.get("summary") or "", _SUMMARY_MAX),
    }


def normalize_pond_items(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        out.append(normalize_pond_item(item, i))
        if len(out) >= _MAX_ITEMS:
            break
    return out


def save_opening_ponds(
    items: list[dict[str, str]],
    *,
    summary: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """写入 sidecar，返回事件 payload。"""
    ponds_id = f"ponds-{uuid4().hex[:8]}"
    body = {
        "ponds_id": ponds_id,
        "summary": _clip(summary, 4096),
        "items": items,
    }
    path = opening_ponds_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return body


def load_opening_ponds(*, workspace_root: Path | None = None) -> dict[str, Any] | None:
    path = opening_ponds_path(workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    items = normalize_pond_items(data.get("items"))
    if len(items) < _MIN_ITEMS:
        return None
    return {
        "ponds_id": str(data.get("ponds_id") or "ponds"),
        "summary": str(data.get("summary") or ""),
        "items": items,
    }


def clear_opening_ponds(*, workspace_root: Path | None = None) -> bool:
    path = opening_ponds_path(workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def format_select_pond_message(item: dict[str, str]) -> str:
    """点选后发给下一 Turn 的用户消息。"""
    lines = [f"按开篇候选「{item.get('title') or item.get('id')}」写第一章。", ""]
    if item.get("who"):
        lines.append(f"跟着谁：{item['who']}")
    if item.get("where"):
        lines.append(f"站在哪：{item['where']}")
    if item.get("want"):
        lines.append(f"眼下要什么：{item['want']}")
    if item.get("chapter_job"):
        lines.append(f"这一章干什么：{item['chapter_job']}")
    return "\n".join(lines).strip()


def format_opening_ponds_block(*, workspace_root: Path | None = None) -> str:
    """volatile：上一组候选，避免换皮重写。"""
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return ""
    lines = [
        "## 上一组开篇候选（不要换皮重写）",
        "换皮 = 换地点职业仍是外面出事、死人、见鬼、开窗。",
        "下一组至少一份：自己发觉能做什么，发生在有人的日子。",
    ]
    for item in data["items"]:
        title = item.get("title") or item.get("id")
        who = item.get("who") or ""
        where = item.get("where") or ""
        bit = " · ".join(p for p in (title, who, where) if p)
        lines.append(f"- {bit}" if bit else f"- {title}")
    return "\n".join(lines)
