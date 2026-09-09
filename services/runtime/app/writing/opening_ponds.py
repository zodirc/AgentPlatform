"""开篇近池候选：结构化交卷，供聊天内点选（像 Plan 清单）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

OPENING_PONDS_REL = Path(".agent") / "work" / "opening_ponds.json"
# 勾选后发给下一回合的短令牌；聊天不画这条气泡。换皮约束在 format_opening_ponds_block。
MORE_PONDS_MESSAGE = "我要其他的"
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_opening_ponds", "stub_echo"})

START_KIND_LABELS: dict[str, str] = {
    "self_notice": "自己发觉能变强",
    "pulled_in": "被卷进已在运转的事",
    "granted_path": "系统/金手指落到身上",
    "world_already": "超凡已是这城的日常",
    "no_extraordinary": "先过日子，超凡往后放",
}
PROMISE_LABELS: dict[str, str] = {
    "power_steps": "变强台阶",
    "costly_truth": "查清会伤人的真相",
    "survive_relation": "在关系里活下去",
    "dread_decode": "解密/恐惧",
    "social_place": "社会位置改变",
}
_START_KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "self_notice": (
        "自己发觉",
        "自己发觉能变强",
        "自己变强",
        "发觉能力",
        "自己发现",
        "身体异常",
        "发觉能做什么",
    ),
    "pulled_in": ("被卷进", "卷进", "已在运转", "拖进"),
    "granted_path": (
        "当场得到",
        "得到能用的路",
        "系统/金手指落到身上",
        "金手指落到",
        "开启系统",
        "系统",
    ),
    "world_already": (
        "一开始就不正常",
        "超凡已是这城的日常",
        "这城本来就在修真",
        "遍地修真",
        "世界已经",
        "机构内部的日常",
    ),
    "no_extraordinary": (
        "没有超凡",
        "本章没有超凡",
        "先过日子，超凡往后放",
        "先过日子",
        "平淡开局",
        "先不过超凡",
    ),
}
_PROMISE_ALIASES: dict[str, tuple[str, ...]] = {
    "power_steps": ("变强", "台阶", "升级"),
    "costly_truth": ("查清", "会伤人的真相", "真相会伤人"),
    "survive_relation": ("关系里活下去", "人情", "把债还上"),
    "dread_decode": ("解密", "恐惧", "克系"),
    "social_place": ("社会位置", "位置改变", "位子"),
}

_OPENING_CHOICE_BLOCK = """## Opening choice (platform)
This turn is a Plan-like picker. Call `propose_opening_ponds` once with 2–3 items.
Each item needs title, who, where, want, start_kind, promise, opening, arc, flavor.
The UI card is a short book plan the user reads: 开篇 / 走向 / 风格.
Do not sell the book as 系统 or 关系 labels. start_kind/promise are contrast only.
Do not list the ponds in the assistant message. Do not call draft_section or
update_outline. The user checks a card (no chat bubble) or 我要其他的.

start_kind (required, unique): self_notice | pulled_in | granted_path |
world_already | no_extraordinary
promise (required, not all identical): power_steps | costly_truth |
survive_relation | dread_decode | social_place
opening = how the book starts (a scene, not a quest checklist)
arc = where the book goes after the opening (mid-book pressure, not the ending bible)
flavor = the whole book's smell in one line

Job changes are not distinct. The handler rejects a set with no 开篇/走向/风格,
duplicate start_kind, all-same promise, reused previous start_kinds, or (for 修真)
发觉+卷入+办证 without 系统 or 过日子. dread_decode is for 灵异/克系.
Do not write a unifying summary (「三条都市修真」).
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
_PLAN_MAX = 400
_FLAVOR_MAX = 160
_PLAN_MIN = 18
_FLAVOR_MIN = 8
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


def _normalize_enum(
    raw: Any,
    labels: dict[str, str],
    aliases: dict[str, tuple[str, ...]],
) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    key = text.lower().replace("-", "_").replace(" ", "_")
    if key in labels:
        return key
    for token, zh in labels.items():
        if text == zh:
            return token
    lowered = text.lower()
    for token, extra in aliases.items():
        for alias in extra:
            if alias.lower() == lowered or alias in text:
                return token
    return ""


def normalize_start_kind(raw: Any) -> str:
    return _normalize_enum(raw, START_KIND_LABELS, _START_KIND_ALIASES)


def normalize_promise(raw: Any) -> str:
    return _normalize_enum(raw, PROMISE_LABELS, _PROMISE_ALIASES)


def start_kind_label(token: str) -> str:
    return START_KIND_LABELS.get(token, token)


def promise_label(token: str) -> str:
    return PROMISE_LABELS.get(token, token)


def ponds_contrast_summary(items: list[dict[str, str]]) -> str:
    """对照用书名气味，不是系统/关系标签。"""
    bits: list[str] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        flavor = str(it.get("flavor") or "").strip()
        if title and flavor:
            bits.append(f"{title}·{flavor}")
        elif flavor:
            bits.append(flavor)
        else:
            kind = start_kind_label(str(it.get("start_kind") or ""))
            promise = promise_label(str(it.get("promise") or ""))
            bit = "·".join(p for p in (kind, promise) if p)
            if bit:
                bits.append(bit)
    return " ｜ ".join(bits)


def normalize_pond_item(raw: dict[str, Any], index: int) -> dict[str, str]:
    """一条近池：书级短计划 + 跟着谁 / 站在哪 / 眼下要什么。"""
    title = _clip(raw.get("title") or raw.get("name") or f"候选 {index + 1}", _TITLE_MAX)
    item_id = _clip(raw.get("id") or f"pond-{index + 1}", 32) or f"pond-{index + 1}"
    start_kind = normalize_start_kind(
        raw.get("start_kind") or raw.get("超凡怎么开始") or ""
    )
    promise = normalize_promise(raw.get("promise") or raw.get("读者买什么") or "")
    opening = _clip(raw.get("opening") or raw.get("开篇") or "", _PLAN_MAX)
    arc = _clip(
        raw.get("arc") or raw.get("走向") or raw.get("全篇走向") or "",
        _PLAN_MAX,
    )
    flavor = _clip(
        raw.get("flavor") or raw.get("风格") or raw.get("全篇风格") or "",
        _FLAVOR_MAX,
    )
    chapter_job = _clip(
        raw.get("chapter_job") or raw.get("这一章干什么") or opening,
        _FIELD_MAX,
    )
    return {
        "id": item_id,
        "title": title or f"候选 {index + 1}",
        "who": _clip(raw.get("who") or raw.get("跟着谁") or "", _FIELD_MAX),
        "where": _clip(raw.get("where") or raw.get("站在哪") or "", _FIELD_MAX),
        "want": _clip(raw.get("want") or raw.get("眼下要什么") or "", _FIELD_MAX),
        "chapter_job": chapter_job,
        "opening": opening,
        "arc": arc,
        "flavor": flavor,
        "start_kind": start_kind,
        "promise": promise,
        "summary": _clip(raw.get("summary") or flavor, _SUMMARY_MAX),
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


def pond_item_event_fields(raw: dict[str, Any], index: int) -> dict[str, str] | None:
    """投影到 opening.ponds 事件：只留 schema 允许的字段。"""
    item = normalize_pond_item(raw, index)
    title = item.get("title") or ""
    if not title.strip():
        return None
    row = {"id": item["id"], "title": title}
    for key in (
        "who",
        "where",
        "want",
        "chapter_job",
        "opening",
        "arc",
        "flavor",
        "summary",
    ):
        val = item.get(key) or ""
        if val:
            row[key] = val
    if item.get("start_kind") in START_KIND_LABELS:
        row["start_kind"] = item["start_kind"]
    if item.get("promise") in PROMISE_LABELS:
        row["promise"] = item["promise"]
    return row


_FANTASY_HINT = re.compile(r"修真|玄幻|仙侠|爽文")
_OCCULT_HINT = re.compile(r"灵异|克系|恐怖|惊悚")
_PLAIN_LEAK = re.compile(r"秘密|盯上|灵异|失踪|无名尸|殡仪|冷藏")
_GIFT_HINT = re.compile(r"系统|金手指|功法|面板")
_WORLD_HINT = re.compile(r"修真|灵气|功法|坊市|境界|灵石|宗门|工分|灵脉")
_EARLY_KINDS = frozenset({"self_notice", "granted_path"})
_NORMAL_KINDS = frozenset({"world_already", "no_extraordinary"})
_GIFT_OR_PLAIN = frozenset({"granted_path", "no_extraordinary"})


def _pond_blob(item: dict[str, str]) -> str:
    return "".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "who",
            "where",
            "want",
            "chapter_job",
            "opening",
            "arc",
            "flavor",
            "summary",
        )
    )


def ponds_reject_reason(
    items: list[dict[str, str]],
    *,
    message: str = "",
    previous_kinds: set[str] | frozenset[str] | None = None,
) -> tuple[str, str] | None:
    """拒共线集合。旧 sidecar 缺字段时不走这条（只在 propose 时调用）。"""
    if len(items) < _MIN_ITEMS:
        return (
            "need_two_ponds",
            "至少交 2 个开篇候选，且 start_kind 不得重复。",
        )
    kinds = [str(it.get("start_kind") or "") for it in items]
    promises = [str(it.get("promise") or "") for it in items]
    if any(not k or not p for k, p in zip(kinds, promises)):
        return (
            "need_start_kind_and_promise",
            "每份都要有 start_kind 和 promise。"
            f" start_kind∈{tuple(START_KIND_LABELS)}；"
            f" promise∈{tuple(PROMISE_LABELS)}。",
        )
    if len(set(kinds)) < len(kinds):
        return (
            "start_kind_collision",
            "start_kind 不得重复。换职业地点不算分开。"
            f" 已交：{kinds}。",
        )
    if len(set(promises)) == 1:
        return (
            "promise_collision",
            "promise 不得全员相同。"
            f" 已交：{promises[0]}。",
        )
    if previous_kinds:
        overlap = sorted(set(kinds) & set(previous_kinds))
        if overlap:
            unused = [
                start_kind_label(k)
                for k in START_KIND_LABELS
                if k not in previous_kinds
            ]
            hint = "、".join(unused) if unused else "（五种都用过了，改 promise 和场面）"
            return (
                "kinds_repeat",
                "上一组已经用过这些 start_kind，换还没用过的。"
                f" 重复：{overlap}。还没用过：{hint}。",
            )
    axis_names = set(START_KIND_LABELS.values()) | set(PROMISE_LABELS.values())
    for it in items:
        opening = str(it.get("opening") or "").strip()
        arc = str(it.get("arc") or "").strip()
        flavor = str(it.get("flavor") or "").strip()
        if flavor in axis_names:
            return (
                "plan_is_axis",
                "风格请写成这本书的气味，不要直接填变强台阶/在关系里活下去这类对照标签。",
            )
        if (
            len(opening) < _PLAN_MIN
            or len(arc) < _PLAN_MIN
            or len(flavor) < _FLAVOR_MIN
        ):
            return (
                "need_book_plan",
                "每份都要有开篇、走向、风格：开篇怎么进、这本书往后怎么走、全篇什么气味。"
                "不要只填系统/关系标签。",
            )
    for it in items:
        blob = _pond_blob(it)
        kind = str(it.get("start_kind") or "")
        if kind == "no_extraordinary" and _PLAIN_LEAK.search(blob):
            return (
                "plain_not_plain",
                "no_extraordinary 必须是先过日子，不能写成殡仪馆/失踪/城市秘密。",
            )
    if _FANTASY_HINT.search(message or ""):
        kind_set = set(kinds)
        if not (kind_set & _EARLY_KINDS) or not (kind_set & _NORMAL_KINDS):
            return (
                "need_normal_opening",
                "修真/玄幻候选要同时有：自己变强或系统/金手指，以及遍地修真或先过日子。",
            )
        if not _OCCULT_HINT.search(message or ""):
            if any(p == "dread_decode" for p in promises):
                return (
                    "dread_not_cultivation",
                    "修真/玄幻默认买变强台阶或社会位置，解密/恐惧留给用户点名灵异、克系时。",
                )
        if len(items) >= 3 and not (kind_set & _GIFT_OR_PLAIN):
            return (
                "need_gift_or_plain",
                "修真/玄幻三份候选必须有系统/金手指或先过日子，不能只交发觉+卷入+遍地办证。",
            )
        for it in items:
            blob = _pond_blob(it)
            kind = str(it.get("start_kind") or "")
            if kind == "granted_path" and not _GIFT_HINT.search(blob):
                return (
                    "gift_not_gift",
                    "granted_path 请写成系统、金手指或功法落到身上，不要收雷/灵异物件。",
                )
            if kind == "world_already" and not _WORLD_HINT.search(blob):
                return (
                    "world_not_cultivation",
                    "world_already 请写成这城本来就在修真（灵气/坊市/功法），不是灵异出事。",
                )
    return None


def save_opening_ponds(
    items: list[dict[str, str]],
    *,
    summary: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """写入 sidecar，返回事件 payload。"""
    ponds_id = f"ponds-{uuid4().hex[:8]}"
    contrast = ponds_contrast_summary(items)
    body = {
        "ponds_id": ponds_id,
        "summary": contrast or _clip(summary, 4096),
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


_COMMIT_TITLE_RE = re.compile(
    r"(?:按开篇候选|采用此开篇|按此开篇)[「『](.+?)[」』]"
)


def format_select_pond_message(item: dict[str, str]) -> str:
    """勾选后发给下一回合的令牌；聊天不画这条气泡。"""
    title = (item.get("title") or item.get("id") or "").strip()
    return f"采用此开篇「{title}」"


def committed_pond_title(message: str) -> str | None:
    text = (message or "").strip()
    if not text:
        return None
    match = _COMMIT_TITLE_RE.search(text)
    title = (match.group(1) if match else "").strip()
    return title or None


def find_committed_pond(
    *,
    message: str,
    workspace_root: Path | None,
) -> dict[str, str] | None:
    title = committed_pond_title(message)
    if not title:
        return None
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return None
    for item in data["items"]:
        if (item.get("title") or item.get("id") or "").strip() == title:
            return item
    return None


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    """volatile：用户只点了选择，卡片正文从 sidecar 灌给模型。"""
    item = find_committed_pond(message=message, workspace_root=workspace_root)
    if not item:
        return ""
    title = item.get("title") or item.get("id") or ""
    lines = [
        "## 已选开篇",
        "用户在卡片上勾选了一份。按下面这份写第一章，不要再出候选。",
        f"书名：{title}",
    ]
    if item.get("opening"):
        lines.append(f"开篇：{item['opening']}")
    if item.get("arc"):
        lines.append(f"走向：{item['arc']}")
    if item.get("flavor"):
        lines.append(f"风格：{item['flavor']}")
    if item.get("who"):
        lines.append(f"跟着谁：{item['who']}")
    if item.get("where"):
        lines.append(f"站在哪：{item['where']}")
    if item.get("want"):
        lines.append(f"眼下要什么：{item['want']}")
    kind = str(item.get("start_kind") or "")
    promise = str(item.get("promise") or "")
    if kind:
        lines.append(f"超凡怎么开始：{start_kind_label(kind)}")
    if promise:
        lines.append(f"读者买什么：{promise_label(promise)}")
    return "\n".join(lines)


def format_opening_ponds_block(*, workspace_root: Path | None = None) -> str:
    """volatile：上一组候选，下一组不得复用同一 start_kind。"""
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return ""
    used = {
        str(item.get("start_kind") or "")
        for item in data["items"]
        if item.get("start_kind")
    }
    unused = [
        start_kind_label(k) for k in START_KIND_LABELS if k not in used
    ]
    unused_line = "、".join(unused) if unused else "五种都用过了，改场面和 promise"
    lines = [
        "## 上一组开篇候选（不要换皮重写）",
        "换皮 = start_kind 与上一组相同，只换职业地点或换一套系统皮。",
        f"下一组必须用还没用过的 start_kind：{unused_line}。",
        "每份仍要写成开篇/走向/风格，不要只交对照标签。",
    ]
    for item in data["items"]:
        title = item.get("title") or item.get("id")
        flavor = item.get("flavor") or ""
        arc = item.get("arc") or ""
        kind = start_kind_label(str(item.get("start_kind") or ""))
        bit = " · ".join(p for p in (title, flavor, kind) if p)
        lines.append(f"- {bit}" if bit else f"- {title}")
        if arc:
            lines.append(f"  走向：{arc}")
    return "\n".join(lines)
