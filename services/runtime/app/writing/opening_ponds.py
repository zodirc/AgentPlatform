"""开篇近池候选：结构化交卷，供聊天内点选（像 Plan 清单）。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

OPENING_PONDS_REL = Path(".agent") / "work" / "opening_ponds.json"
COMMITTED_POND_REL = Path(".agent") / "work" / "committed_pond.json"
MORE_PONDS_MESSAGE = "我要其他的"
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_opening_ponds", "stub_echo"})
# Same Turn may repair once; a second reject stops (user says 我看看).
_POND_REPAIR_MAX = 1
_POND_REJECTS: dict[str, int] = {}
_POND_REJECT_USER_SUMMARY = "开篇候选这轮没交成。请再说一次「我看看」。"
_POND_REPAIR_SUMMARY = "开篇候选这轮没交成。请按 detail 改字段后再交一次，不要写进聊天。"

logger = logging.getLogger(__name__)


def wants_more_ponds(message: str) -> bool:
    """只有整句「我要其他的」才远离上一组书；「我看看」是新点选。"""
    return (message or "").strip() == MORE_PONDS_MESSAGE


def _pond_reject_key(turn_id: object | None) -> str | None:
    if turn_id is None:
        return None
    key = str(turn_id).strip()
    if not key or key == "None":
        return None
    return key


def clear_pond_rejects(turn_id: object | None = None) -> None:
    """成功交卷后清计数；测试也可整表清空。"""
    if turn_id is None:
        _POND_REJECTS.clear()
        return
    key = _pond_reject_key(turn_id)
    if key:
        _POND_REJECTS.pop(key, None)


def note_pond_reject(
    turn_id: object | None, rejected: tuple[str, str] | None
) -> dict[str, Any] | None:
    """有 turn_id 时允许同轮改一次；拒因放 detail，Don't 不进 summary。"""
    if rejected is None:
        return None
    code, msg = rejected
    key = _pond_reject_key(turn_id)
    if key is None:
        count = _POND_REPAIR_MAX + 1
    else:
        if len(_POND_REJECTS) > 256:
            _POND_REJECTS.clear()
        count = _POND_REJECTS.get(key, 0) + 1
        _POND_REJECTS[key] = count
    exhausted = count > _POND_REPAIR_MAX
    return {
        "status": "error",
        "error": code,
        "detail": msg,
        "summary": _POND_REJECT_USER_SUMMARY if exhausted else _POND_REPAIR_SUMMARY,
        "stop_retry": exhausted,
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
# 灵契 / 功簿 / 仙籍 / 工分 会实体化成世界设定，只留给模型抄标签时出现；不作归一抓手。
_PRICE_AXIS_ALIASES: dict[str, tuple[str, ...]] = {
    "lifespan": ("用寿或命结账", "烧寿", "扣寿", "命税", "寿命"),
    "memory": ("用记忆结账", "记忆税", "忘掉"),
    "contract": ("用契或名册结账",),
    "status": ("用名分或籍结账", "名分"),
    "none": ("不当场拿命或记忆结账", "无明码"),
}

_OPENING_CHOICE_REL = (
    Path(__file__).resolve().parents[1]
    / "scenarios"
    / "writing"
    / "templates"
    / "opening_choice.md"
)

_TITLE_MAX = 80
_FIELD_MAX = 240
_SUMMARY_MAX = 160
_PLAN_MAX = 400
_FLAVOR_MAX = 400
_PRICE_MAX = 160
_PLAN_MIN = 18
_FLAVOR_MIN = 8
_SELF_NOTE_MAX = 160
_SOCIAL_SPACE_MAX = 80
_ENGINE_NOTE_MAX = 160
_MIN_ITEMS = 2
_MAX_ITEMS = 4


def opening_choice_block() -> str:
    """volatile：开篇点选纪律（不焊进 system 前缀）。拒因目录在 handler，不抄进 prompt。"""
    try:
        return _OPENING_CHOICE_REL.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "## Opening choice (platform)\n"
            "Call `propose_opening_ponds` once with 2–3 items. "
            "Leave the assistant message empty. "
            "Write title / flavor / opening first. Cards are the deliverable."
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
    """一条近池：书名 + 这本书 + 开篇；自述在后。"""
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
    book_self_note = _clip(
        raw.get("book_self_note") or raw.get("这本书在玩什么") or "",
        _SELF_NOTE_MAX,
    )
    social_space = _clip(
        raw.get("social_space") or raw.get("社会角落") or "",
        _SOCIAL_SPACE_MAX,
    )
    engine_note = _clip(
        raw.get("engine_note") or raw.get("为什么能一直写") or "",
        _ENGINE_NOTE_MAX,
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
        "book_self_note": book_self_note,
        "social_space": social_space,
        "engine_note": engine_note,
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
    """投影到 opening.ponds 事件：只留 schema 允许的字段。自述不进事件。"""
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


def fill_pond_defaults(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """只补节奏槽：source_trust / first_conflict_at。轴缺就留空，不贴、不去重。"""
    out: list[dict[str, str]] = []
    for i, item in enumerate(items):
        row = dict(item)
        trust = str(row.get("source_trust") or "")
        if trust not in SOURCE_TRUST_LABELS:
            trust = ("dubious", "trusted", "false")[i % 3]
        row["source_trust"] = trust
        conflict = str(row.get("first_conflict_at") or "")
        if conflict not in FIRST_CONFLICT_AT_LABELS:
            conflict = ("first_300", "first_1000", "chapter_one")[i % 3]
        row["first_conflict_at"] = conflict
        out.append(row)
    return out


def _axis_label_set() -> set[str]:
    return (
        set(START_KIND_LABELS.values())
        | set(PROMISE_LABELS.values())
        | set(PRICE_AXIS_LABELS.values())
    )


def ponds_reject_reason(
    items: list[dict[str, str]],
    *,
    message: str = "",
    against: list[dict[str, Any]] | None = None,
    similarity: dict[str, Any] | None = None,
    shadow: bool | None = None,
    workspace_root: Path | None = None,
    skip_ledger: bool = True,
) -> tuple[str, str] | None:
    """拒共线集合。轴不再作为比较键。"""
    from app.settings import settings

    _ = (skip_ledger, workspace_root)
    if len(items) < _MIN_ITEMS:
        return ("need_two_ponds", "至少交 2 个开篇候选。")
    conflicts = [str(it.get("first_conflict_at") or "") for it in items]
    if sum(1 for c in conflicts if c == "later") > 1:
        return (
            "later_over_quota",
            "first_conflict_at=later 至多一份，不要把冲突都放到第一章之后。",
        )
    axis_names = _axis_label_set()
    for it in items:
        opening = str(it.get("opening") or "").strip()
        flavor = str(it.get("flavor") or "").strip()
        note = str(it.get("book_self_note") or "").strip()
        if flavor in axis_names or note in axis_names:
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
    trusts = [str(it.get("source_trust") or "") for it in items]
    if len(items) >= 3 and all(t == "trusted" for t in trusts):
        logger.info(
            "pond trust_all_clean shadow n=%s (not rejected)",
            len(items),
        )
    is_shadow = settings.ponds_similarity_shadow if shadow is None else bool(shadow)
    snap = similarity
    if snap is None:
        from app.writing.pond_similarity import compute_pond_similarity

        snap = compute_pond_similarity(
            items, against=against or [], shadow=is_shadow
        )
    from app.writing.pond_similarity import near_rejected_reject, same_book_reject

    same = same_book_reject(snap)
    if same:
        if is_shadow:
            logger.info("ponds_same_book shadow %s", same[1])
        else:
            return same
    if wants_more_ponds(message) or against:
        near = near_rejected_reject(snap)
        if near:
            if is_shadow:
                logger.info("ponds_near_rejected shadow %s", near[1])
            else:
                return near
    return None


def rank_opening_ponds(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """内容口味排序已删；保持提交顺序。"""
    return list(items)


def save_opening_ponds(
    items: list[dict[str, str]],
    *,
    summary: str = "",
    similarity: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """写入 sidecar，返回事件 payload。"""
    from app.writing.pond_similarity import sidecar_similarity

    ponds_id = f"ponds-{uuid4().hex[:8]}"
    contrast = ponds_contrast_summary(items)
    body: dict[str, Any] = {
        "ponds_id": ponds_id,
        "summary": contrast or _clip(summary, 4096),
        "items": items,
    }
    if similarity:
        body["similarity"] = sidecar_similarity(similarity)
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
    out: dict[str, Any] = {
        "ponds_id": str(data.get("ponds_id") or "ponds"),
        "summary": str(data.get("summary") or ""),
        "items": items,
    }
    if isinstance(data.get("similarity"), dict):
        out["similarity"] = data["similarity"]
    return out


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
    from app.writing.pond_history import clear_rejected_ponds
    from app.writing.story_state import seed_identity_from_pond

    seed_identity_from_pond(item, workspace_root=workspace_root)
    clear_rejected_ponds(workspace_root=workspace_root)
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


def format_opening_ponds_block(
    *,
    workspace_root: Path | None = None,
    mode: str = "browse",
) -> str:
    from app.writing.pond_prompts import format_opening_ponds_block as _impl

    if mode not in {"more", "browse"}:
        mode = "browse"
    return _impl(workspace_root=workspace_root, mode=mode)  # type: ignore[arg-type]


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    from app.writing.pond_prompts import format_committed_pond_block as _impl

    return _impl(message=message, workspace_root=workspace_root)


def format_user_axis_intent_block(message: str) -> str:
    from app.writing.pond_prompts import format_user_axis_intent_block as _impl

    return _impl(message)
