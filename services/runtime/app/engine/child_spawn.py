"""Parent-Turn child spawn specs (hang/join lives in the controller, not the while)."""

from __future__ import annotations

import json
from typing import Any

from app.engine.state import tool_result_message
from app.tools.delegate_context import current_delegate_depth


def should_spawn_child(*, agent_type: str, wait: Any) -> bool:
    """Park the parent Turn instead of nesting ``engine.run`` in the tool slot.

    Nested delegates (depth>0) always run synchronously. ``wait=false`` is the
    escape hatch back to the old blocking nested engine.
    """
    del agent_type
    if current_delegate_depth() > 0:
        return False
    if wait is False or str(wait).strip().lower() in {"false", "0", "no"}:
        return False
    return True


def child_spec_from_call(
    *,
    tool_call_id: str,
    step_index: int,
    arguments: dict[str, Any],
    turn_id: Any,
    run_id: Any,
) -> dict[str, Any]:
    raw = arguments if isinstance(arguments, dict) else {}
    return {
        "tool_call_id": str(tool_call_id),
        "step_index": int(step_index),
        "task": str(raw.get("task") or ""),
        "agent_type": str(raw.get("agent_type") or "explore").strip() or "explore",
        "context": str(raw.get("context") or ""),
        "context_refs": list(raw.get("context_refs") or []),
        "paths": list(raw.get("paths") or []),
        "turn_id": str(turn_id) if turn_id is not None else "",
        "run_id": str(run_id) if run_id is not None else "",
    }


def splice_child_results(
    messages: list[dict[str, Any]],
    results_by_id: dict[str, dict[str, Any]],
) -> None:
    """Put child ``tool_result`` rows in tool_use order among already-appended results."""
    assistant_idx = -1
    uses: list[str] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        ids = [
            str(b.get("id") or "")
            for b in (msg.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if ids:
            assistant_idx = i
            uses = ids
    if assistant_idx < 0 or not uses:
        return
    existing: dict[str, dict[str, Any]] = {}
    tail = assistant_idx + 1
    while tail < len(messages) and messages[tail].get("role") == "tool":
        for block in messages[tail].get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if tid:
                existing[tid] = messages[tail]
        tail += 1
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in uses:
        if tid in seen:
            continue
        seen.add(tid)
        child = results_by_id.get(tid)
        if child is not None:
            ordered.append(
                tool_result_message(
                    tid,
                    json.dumps(child, ensure_ascii=False, default=str),
                    is_error=str(child.get("status") or "") in {"failed", "error", "cancelled"},
                )
            )
        elif tid in existing:
            ordered.append(existing[tid])
    messages[assistant_idx + 1 : tail] = ordered
