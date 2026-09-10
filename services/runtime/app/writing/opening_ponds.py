"""开篇近池候选：结构化交卷，供聊天内点选（像 Plan 清单）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

OPENING_PONDS_REL = Path(".agent") / "work" / "opening_ponds.json"
COMMITTED_POND_REL = Path(".agent") / "work" / "committed_pond.json"
MORE_PONDS_MESSAGE = "我要其他的"
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_opening_ponds", "stub_echo"})


def wants_more_ponds(message: str) -> bool:
    """只有「我要其他的」才继承上一组 start_kind / price_axis；「我看看」是新点选。"""
    return (message or "").strip() == MORE_PONDS_MESSAGE


def note_pond_reject(
    turn_id: object | None, rejected: tuple[str, str] | None
) -> dict[str, Any] | None:
    """Handler 一拒就停转。拒因留给 error 码，不把 Don't 写进 turn.completed。"""
    del turn_id
    if rejected is None:
        return None
    code, _msg = rejected
    return {
        "status": "error",
        "error": code,
        "summary": "开篇候选这轮没交成。请再说一次「我看看」。",
        "stop_retry": True,
    }


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
SOURCE_TRUST_LABELS: dict[str, str] = {
    "trusted": "来源可信",
    "dubious": "来源不可信",
    "false": "来源是假的",
}
FIRST_CONFLICT_AT_LABELS: dict[str, str] = {
    "first_300": "前300字",
    "first_1000": "前1000字",
    "chapter_one": "第一章内",
    "later": "第一章之后",
}
PRICE_AXIS_LABELS: dict[str, str] = {
    "lifespan": "用寿或命结账",
    "memory": "用记忆结账",
    "contract": "用契或名册结账",
    "status": "用名分或籍结账",
    "none": "不当场拿命或记忆结账",
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
_SOURCE_TRUST_ALIASES: dict[str, tuple[str, ...]] = {
    "false": ("来源是假的", "虚假", "是假的"),
    "dubious": ("来源不可信", "不可信", "来源可疑", "骗子师父"),
    "trusted": ("来源可信", "可信"),
}
_FIRST_CONFLICT_AT_ALIASES: dict[str, tuple[str, ...]] = {
    "later": ("第一章之后", "第一章后", "更后"),
    "first_300": ("前300字", "前 300 字"),
    "first_1000": ("前1000字", "前 1000 字"),
    "chapter_one": ("第一章内", "本章内"),
}
_PRICE_AXIS_ALIASES: dict[str, tuple[str, ...]] = {
    "lifespan": ("用寿或命结账", "烧寿", "扣寿", "命税", "寿命"),
    "memory": ("用记忆结账", "记忆税", "忘掉"),
    "contract": ("用契或名册结账", "灵契", "功簿"),
    "status": ("用名分或籍结账", "名分", "仙籍", "工分"),
    "none": ("不当场拿命或记忆结账", "无明码"),
}

_OPENING_CHOICE_REL = (
    Path(__file__).resolve().parents[1]
    / "scenarios"
    / "writing"
    / "templates"
    / "opening_choice.md"
)


def opening_choice_block() -> str:
    """volatile：开篇点选纪律（不焊进 system 前缀）。拒因目录在 handler，不抄进 prompt。"""
    try:
        return _OPENING_CHOICE_REL.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "## Opening choice (platform)\n"
            "Call `propose_opening_ponds` once with 2–3 items. "
            "Leave the assistant message empty. "
            "Each needs title, flavor (这本书), opening, start_kind, promise, "
            "price_axis, source_trust, first_conflict_at. Do not list ponds in chat."
        )


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
_FLAVOR_MAX = 400
_PRICE_MAX = 160
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


def committed_pond_path(workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / COMMITTED_POND_REL


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


def normalize_source_trust(raw: Any) -> str:
    return _normalize_enum(raw, SOURCE_TRUST_LABELS, _SOURCE_TRUST_ALIASES)


def normalize_first_conflict_at(raw: Any) -> str:
    return _normalize_enum(raw, FIRST_CONFLICT_AT_LABELS, _FIRST_CONFLICT_AT_ALIASES)


def normalize_price_axis(raw: Any) -> str:
    return _normalize_enum(raw, PRICE_AXIS_LABELS, _PRICE_AXIS_ALIASES)


def start_kind_label(token: str) -> str:
    return START_KIND_LABELS.get(token, token)


def promise_label(token: str) -> str:
    return PROMISE_LABELS.get(token, token)


def source_trust_label(token: str) -> str:
    return SOURCE_TRUST_LABELS.get(token, token)


def first_conflict_at_label(token: str) -> str:
    return FIRST_CONFLICT_AT_LABELS.get(token, token)


def price_axis_label(token: str) -> str:
    return PRICE_AXIS_LABELS.get(token, token)


def ponds_contrast_summary(items: list[dict[str, str]]) -> str:
    """对照用书名，不把整段这本书糊在顶栏。"""
    bits: list[str] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if title:
            bits.append(title)
    return " ｜ ".join(bits)


def normalize_pond_item(raw: dict[str, Any], index: int) -> dict[str, str]:
    """一条近池：书名 + 这本书 + 开篇。"""
    title = _clip(raw.get("title") or raw.get("name") or f"候选 {index + 1}", _TITLE_MAX)
    item_id = _clip(raw.get("id") or f"pond-{index + 1}", 32) or f"pond-{index + 1}"
    start_kind = normalize_start_kind(
        raw.get("start_kind") or raw.get("超凡怎么开始") or ""
    )
    promise = normalize_promise(raw.get("promise") or raw.get("读者买什么") or "")
    source_trust = normalize_source_trust(
        raw.get("source_trust") or raw.get("来源可信") or raw.get("力的来源") or ""
    )
    first_conflict_at = normalize_first_conflict_at(
        raw.get("first_conflict_at") or raw.get("第一场冲突") or ""
    )
    price_axis = normalize_price_axis(
        raw.get("price_axis") or raw.get("付账轴") or raw.get("谁付账") or ""
    )
    opening = _clip(raw.get("opening") or raw.get("开篇") or "", _PLAN_MAX)
    arc = _clip(
        raw.get("arc") or raw.get("走向") or raw.get("全篇走向") or "",
        _PLAN_MAX,
    )
    flavor = _clip(
        raw.get("flavor")
        or raw.get("这本书")
        or raw.get("book")
        or raw.get("风格")
        or raw.get("全篇风格")
        or "",
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
        "price": _clip(raw.get("price") or raw.get("代价") or raw.get("账单") or "", _PRICE_MAX),
        "start_kind": start_kind,
        "promise": promise,
        "source_trust": source_trust,
        "first_conflict_at": first_conflict_at,
        "price_axis": price_axis,
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
        "price",
        "summary",
    ):
        val = item.get(key) or ""
        if val:
            row[key] = val
    if item.get("start_kind") in START_KIND_LABELS:
        row["start_kind"] = item["start_kind"]
    if item.get("promise") in PROMISE_LABELS:
        row["promise"] = item["promise"]
    if item.get("source_trust") in SOURCE_TRUST_LABELS:
        row["source_trust"] = item["source_trust"]
    if item.get("first_conflict_at") in FIRST_CONFLICT_AT_LABELS:
        row["first_conflict_at"] = item["first_conflict_at"]
    if item.get("price_axis") in PRICE_AXIS_LABELS:
        row["price_axis"] = item["price_axis"]
    return row


_FANTASY_HINT = re.compile(r"修真|玄幻|仙侠|爽文")
# 词表只认殡仪馆/失踪那套换皮，不把「秘密」「盯上」当过日子禁词。
_PLAIN_LEAK = re.compile(r"殡仪|冷藏|无名尸|失踪者|失踪|城市秘密|太平间|告别厅|灵异")
_GIFT_HINT = re.compile(r"系统|金手指|功法|面板|异能|能力|觉醒")
_WORLD_HINT = re.compile(
    r"修真|灵气|功法|坊市|境界|灵石|宗门|工分|灵脉|"
    r"异能|能力者|觉醒"
)
_EARLY_KINDS = frozenset({"self_notice", "granted_path", "pulled_in"})


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


def plain_item_leaks(item: dict[str, str]) -> bool:
    """过日子写成殡仪馆/失踪/解密恐惧：这一份不诚实，不是整组题材错了。"""
    if str(item.get("start_kind") or "") != "no_extraordinary":
        return False
    if str(item.get("promise") or "") == "dread_decode":
        return True
    return bool(_PLAIN_LEAK.search(_pond_blob(item)))


def drop_leaking_plain_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """编辑侧丢掉不诚实的过日子卡，剩下的仍交给用户点选。"""
    return [it for it in items if not plain_item_leaks(it)]


def ponds_reject_reason(
    items: list[dict[str, str]],
    *,
    message: str = "",
    previous_kinds: set[str] | frozenset[str] | None = None,
    previous_axes: set[str] | frozenset[str] | None = None,
    workspace_root: Path | None = None,
) -> tuple[str, str] | None:
    """拒共线集合。旧 sidecar 缺字段时不走这条（只在 propose 时调用）。"""
    if len(items) < _MIN_ITEMS:
        return (
            "need_two_ponds",
            "至少交 2 个开篇候选，且 start_kind 不得重复。",
        )
    kinds = [str(it.get("start_kind") or "") for it in items]
    promises = [str(it.get("promise") or "") for it in items]
    axes = [str(it.get("price_axis") or "") for it in items]
    if any(not k or not p for k, p in zip(kinds, promises)):
        return (
            "need_start_kind_and_promise",
            "每份都要有 start_kind 和 promise。"
            f" start_kind∈{tuple(START_KIND_LABELS)}；"
            f" promise∈{tuple(PROMISE_LABELS)}。",
        )
    if any(a not in PRICE_AXIS_LABELS for a in axes):
        return (
            "need_price_axis",
            "每份都要有 price_axis（这本书拿什么结账）。"
            f" price_axis∈{tuple(PRICE_AXIS_LABELS)}。"
            "同一组不得重复。换工种地点不算换轴。",
        )
    if (
        _FANTASY_HINT.search(message or "")
        and len(items) >= 3
        and sum(1 for k in kinds if k == "no_extraordinary") > 1
    ):
        return (
            "plain_over_quota",
            "先过日子至多一份，三份里不要两份都在过普通日子。",
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
    if len(set(axes)) < len(axes):
        return (
            "price_axis_collision",
            "price_axis 不得重复。换矿井药铺不算换引擎。"
            f" 已交：{axes}。",
        )
    trusts = [str(it.get("source_trust") or "") for it in items]
    if any(t not in SOURCE_TRUST_LABELS for t in trusts):
        return (
            "need_source_trust",
            (
                "每份都要有 source_trust。"
                f" source_trust∈{tuple(SOURCE_TRUST_LABELS)}。"
            ),
        )
    if len(items) >= 3 and all(t == "trusted" for t in trusts):
        return (
            "trust_all_clean",
            "三份里至少一份的力来源不可信（source_trust 为 dubious 或 false）。",
        )
    conflicts = [str(it.get("first_conflict_at") or "") for it in items]
    if any(c not in FIRST_CONFLICT_AT_LABELS for c in conflicts):
        return (
            "need_first_conflict_at",
            (
                "每份都要写清第一场冲突位置（first_conflict_at）。"
                f" first_conflict_at∈{tuple(FIRST_CONFLICT_AT_LABELS)}。"
            ),
        )
    if sum(1 for c in conflicts if c == "later") > 1:
        return (
            "later_over_quota",
            "first_conflict_at=later 至多一份，不要把冲突都放到第一章之后。",
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
    if previous_axes:
        axis_overlap = sorted(set(axes) & set(previous_axes))
        if axis_overlap:
            unused = [
                price_axis_label(k)
                for k in PRICE_AXIS_LABELS
                if k not in previous_axes
            ]
            hint = "、".join(unused) if unused else "（付账轴用过了，改 none 以外的轴）"
            return (
                "price_axis_repeat",
                "上一组已经用过这些 price_axis，换还没用过的。"
                f" 重复：{axis_overlap}。还没用过：{hint}。",
            )
    axis_names = (
        set(START_KIND_LABELS.values())
        | set(PROMISE_LABELS.values())
        | set(PRICE_AXIS_LABELS.values())
    )
    for it in items:
        opening = str(it.get("opening") or "").strip()
        flavor = str(it.get("flavor") or "").strip()
        if flavor in axis_names:
            return (
                "plan_is_axis",
                "这本书不要直接填变强台阶/在关系里活下去这类对照标签。",
            )
        if len(opening) < _PLAN_MIN or len(flavor) < _FLAVOR_MIN:
            return (
                "need_book_plan",
                "每份都要有这本书和开篇：这本书在玩什么、开篇怎么进。"
                "不要拆成账单/走向/气味，不要只填系统/关系标签。",
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
        if not previous_kinds:
            if not (kind_set & _EARLY_KINDS):
                return (
                    "need_normal_opening",
                    "修真/玄幻至少要有一份自己发觉、被卷入、或系统/金手指。"
                    "不要两份都是过日子或只写世界已有修士。",
                )
        for it in items:
            blob = _pond_blob(it)
            kind = str(it.get("start_kind") or "")
            if kind == "granted_path" and not _GIFT_HINT.search(blob):
                return (
                    "gift_not_gift",
                    "granted_path 请写成系统、金手指、功法或异能落到身上，不要收雷/灵异物件。",
                )
            if kind == "world_already" and not _WORLD_HINT.search(blob):
                return (
                    "world_not_cultivation",
                    "world_already 请写成超凡已经混在人群里（异能者/修士），不是灵异出事，也不是地铁在供能。",
                )
    from app.writing.ledger import pond_vector, too_close_to_ledger

    close = too_close_to_ledger(
        [pond_vector(it) for it in items],
        workspace_root=_workspace(workspace_root),
    )
    if close:
        return close
    return None


def rank_opening_ponds(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """内容口味排序已删；保持提交顺序。"""
    return list(items)


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


def save_committed_pond(
    item: dict[str, str],
    *,
    workspace_root: Path | None = None,
) -> Path:
    path = committed_pond_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def load_committed_pond(*, workspace_root: Path | None = None) -> dict[str, str] | None:
    path = committed_pond_path(workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    title = str(data.get("title") or data.get("id") or "").strip()
    if not title:
        return None
    return normalize_pond_item(data, 0)


def clear_committed_pond(*, workspace_root: Path | None = None) -> bool:
    path = committed_pond_path(workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


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
    if title:
        data = load_opening_ponds(workspace_root=workspace_root)
        if data:
            for item in data["items"]:
                if (item.get("title") or item.get("id") or "").strip() == title:
                    save_committed_pond(item, workspace_root=workspace_root)
                    return item
        saved = load_committed_pond(workspace_root=workspace_root)
        if saved and (saved.get("title") or saved.get("id") or "").strip() == title:
            return saved
        return None
    return load_committed_pond(workspace_root=workspace_root)


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    """volatile：用户只点了选择，卡片正文从 sidecar 灌给模型。"""
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
    trust = str(item.get("source_trust") or "")
    if trust:
        lines.append(f"力的来源：{source_trust_label(trust)}")
    if item.get("who"):
        lines.append(f"棋盘位：{item['who']}")
    if item.get("where"):
        lines.append(f"站在哪：{item['where']}")
    if item.get("want"):
        lines.append(f"入口（不是这本书要解决的事）：{item['want']}")
    kind = str(item.get("start_kind") or "")
    promise = str(item.get("promise") or "")
    axis = str(item.get("price_axis") or "")
    if kind:
        lines.append(f"超凡怎么开始：{start_kind_label(kind)}")
    if promise:
        lines.append(f"读者买什么：{promise_label(promise)}")
    if axis:
        lines.append(f"拿什么结账：{price_axis_label(axis)}")
    return "\n".join(lines)


def format_opening_ponds_block(*, workspace_root: Path | None = None) -> str:
    """volatile：上一组候选，下一组不得复用同一 start_kind / price_axis。"""
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return ""
    used_k = {str(i.get("start_kind") or "") for i in data["items"] if i.get("start_kind")}
    used_a = {str(i.get("price_axis") or "") for i in data["items"] if i.get("price_axis")}
    unused_k = "、".join(
        start_kind_label(k) for k in START_KIND_LABELS if k not in used_k
    ) or "改场面和 promise"
    unused_a = "、".join(
        price_axis_label(k) for k in PRICE_AXIS_LABELS if k not in used_a
    ) or "改 none 以外的轴"
    lines = [
        "## 上一组开篇候选（不要换皮重写）",
        "换皮 = start_kind 或 price_axis 与上一组相同，只换职业地点。",
        f"下一组必须用还没用过的 start_kind：{unused_k}；price_axis：{unused_a}。",
        "下一组写成书名 + 这本书 + 开篇，不要再拆账单/走向/气味。",
        "每份仍要是一本不同的书，不要只交对照标签。",
    ]
    for item in data["items"]:
        title = item.get("title") or item.get("id")
        flavor = item.get("flavor") or ""
        kind = start_kind_label(str(item.get("start_kind") or ""))
        bit = " · ".join(p for p in (title, flavor, kind) if p)
        lines.append(f"- {bit}" if bit else f"- {title}")
    return "\n".join(lines)
