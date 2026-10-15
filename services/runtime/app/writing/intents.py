"""结构化意图。两只接头把点选落到作品状态，再给模型一条普通消息。壳不拼句子，内核也不再把句子拆回点选。"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.writing_host.errors import InvalidIntent

_CHOICE: ContextVar[dict[str, str] | None] = ContextVar("writing_turn_choice", default=None)

_KINDS = {
    "select_pond",
    "more_ponds",
    "confirm_plan",
    "accept_patch",
    "reject_patch",
}


def preferred_plan_phase(intent_phase: str | None, caller_phase: str | None) -> str | None:
    """意图给出的相位优先。confirm_plan 的 executing 不被壳上残留的 planning 盖掉。"""
    return intent_phase or caller_phase


def turn_choice() -> dict[str, str] | None:
    return _CHOICE.get()


def clear_turn_choice() -> None:
    _CHOICE.set(None)


def resolve_intent(
    intent: dict[str, Any] | None,
    *,
    message: str = "",
    workspace_root: Path | None = None,
    before_apply: Callable[[], None] | None = None,
) -> tuple[str, str | None]:
    """返回 ``(用户消息, plan_phase)``。

    开篇点选按 ``ponds_id`` / ``item_id`` 写入已选作品。换一组、采纳或放弃修订记在本回合的选择上。
    引用的 id 对不上当前候选时抛 ``InvalidIntent``，不猜测。
    ``plan_phase`` 为 None 时沿用调用方原来的相位。
    校验通过后、写入作品之前调用 ``before_apply``，供接头先留回合快照。
    """
    clear_turn_choice()
    if not intent:
        text = (message or "").strip()
        if not text:
            raise InvalidIntent(detail="empty turn")
        _apply_baseline(before_apply)
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
        item = _lookup_pond(ponds_id, item_id, workspace_root)
        title = str(item.get("title") or item_id).strip()
        text = f"就用这个开篇：{title}"
        _apply_baseline(before_apply)
        from app.writing.opening_ponds import save_committed_pond

        save_committed_pond(item, workspace_root=workspace_root)
        _CHOICE.set({"kind": "select_pond", "ponds_id": ponds_id, "item_id": item_id})
    elif kind == "more_ponds":
        ponds_id = str(intent.get("ponds_id") or "").strip()
        if not ponds_id:
            raise InvalidIntent(detail="more_ponds")
        _require_current_ponds(ponds_id, workspace_root)
        text = note or "再给一组开篇"
        _apply_baseline(before_apply)
        _CHOICE.set({"kind": "more_ponds", "ponds_id": ponds_id})
    elif kind == "confirm_plan":
        plan_id = str(intent.get("plan_id") or "").strip()
        if not plan_id:
            raise InvalidIntent(detail="confirm_plan")
        _require_current_plan(plan_id, workspace_root)
        _apply_baseline(before_apply)
        return note or "按此执行", "executing"
    elif kind == "accept_patch":
        patch_id = str(intent.get("patch_id") or "").strip()
        if not patch_id:
            raise InvalidIntent(detail="accept_patch")
        _require_pending_patch(patch_id, workspace_root)
        text = f"采用这个修订 {patch_id}"
        _apply_baseline(before_apply)
        _CHOICE.set({"kind": "accept_patch", "patch_id": patch_id})
    else:
        patch_id = str(intent.get("patch_id") or "").strip()
        if not patch_id:
            raise InvalidIntent(detail="reject_patch")
        _require_pending_patch(patch_id, workspace_root)
        text = f"不用这个修订 {patch_id}"
        _apply_baseline(before_apply)
        from app.writing.candidates import drop_pending_patch

        drop_pending_patch(patch_id=patch_id, workspace_root=workspace_root)
        _CHOICE.set({"kind": "reject_patch", "patch_id": patch_id})
    if note and text != note:
        text = f"{text}\n{note}"
    return text, None


def _apply_baseline(before_apply: Callable[[], None] | None) -> None:
    if before_apply is not None:
        before_apply()


def _require_current_ponds(ponds_id: str, workspace_root: Path | None) -> None:
    from app.writing.opening_ponds import load_opening_ponds

    ponds = load_opening_ponds(workspace_root=workspace_root)
    if not ponds or str(ponds.get("ponds_id") or "") != ponds_id:
        raise InvalidIntent(detail="more_ponds")


def _require_current_plan(plan_id: str, workspace_root: Path | None) -> None:
    from app.writing.candidates import load_turn_plan

    plan = load_turn_plan(workspace_root=workspace_root)
    if not plan or str(plan.get("plan_id") or "") != plan_id:
        raise InvalidIntent(detail="confirm_plan")


def _require_pending_patch(patch_id: str, workspace_root: Path | None) -> None:
    from app.writing.candidates import latest_pending_patch

    current = latest_pending_patch(workspace_root=workspace_root)
    if not current or str(current.get("patch_id") or "") != patch_id:
        raise InvalidIntent(detail="patch")


def _lookup_pond(
    ponds_id: str, item_id: str, workspace_root: Path | None
) -> dict[str, Any]:
    from app.writing.opening_ponds import load_opening_ponds

    data = load_opening_ponds(workspace_root=workspace_root)
    items = list((data or {}).get("items") or [])
    matched = str((data or {}).get("ponds_id") or "") == ponds_id
    item = next((row for row in items if str(row.get("id") or "") == item_id), None)
    if not matched or not isinstance(item, dict):
        raise InvalidIntent(detail="select_pond")
    return item
