"""结构化意图。两只接头把点选变成模型能读的消息，壳不拼句子。"""

from __future__ import annotations

from typing import Any

from app.writing_host.errors import InvalidIntent

_KINDS = {
    "select_pond",
    "more_ponds",
    "confirm_plan",
    "accept_patch",
    "reject_patch",
}


def resolve_intent(intent: dict[str, Any] | None, *, message: str = "") -> tuple[str, str | None]:
    """返回 ``(用户消息, plan_phase)``。

    ``plan_phase`` 为 None 时沿用调用方原来的相位。
    引用的 id 为空则抛 ``InvalidIntent``，不猜测最近一次候选。
    """
    if not intent:
        text = (message or "").strip()
        if not text:
            raise InvalidIntent(detail="empty turn")
        return text, None
    kind = str(intent.get("kind") or "").strip()
    if kind not in _KINDS:
        raise InvalidIntent(detail=kind or "missing kind")
    note = (message or "").strip()
    if kind == "select_pond":
        item_id = str(intent.get("item_id") or "").strip()
        ponds_id = str(intent.get("ponds_id") or "").strip()
        if not item_id or not ponds_id:
            raise InvalidIntent(detail="select_pond")
        text = f"采用此开篇「{item_id}」"
    elif kind == "more_ponds":
        if not str(intent.get("ponds_id") or "").strip():
            raise InvalidIntent(detail="more_ponds")
        text = "我要其他的"
    elif kind == "confirm_plan":
        if not str(intent.get("plan_id") or "").strip():
            raise InvalidIntent(detail="confirm_plan")
        text = note or "按此执行"
        return text, "executing"
    elif kind == "accept_patch":
        patch_id = str(intent.get("patch_id") or "").strip()
        if not patch_id:
            raise InvalidIntent(detail="accept_patch")
        text = f"采用补丁「{patch_id}」"
    else:
        patch_id = str(intent.get("patch_id") or "").strip()
        if not patch_id:
            raise InvalidIntent(detail="reject_patch")
        text = f"不采用补丁「{patch_id}」"
    if note and kind not in {"confirm_plan"}:
        text = f"{text}\n{note}"
    return text, None
