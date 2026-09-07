"""Turn 状态与 Run 状态/终止原因映射（投影辅助）。

``turns.status`` 与 ``runs.status`` 枚举不完全一致；终态事件 payload 可携带
``termination_reason`` 覆盖默认推断。
"""

from __future__ import annotations

TURN_TO_RUN_STATUS: dict[str, str] = {
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "waiting_approval": "interrupted",
    "waiting_child": "running",
    "pending": "accepted",
    "running": "running",
}


def map_turn_to_run_status(turn_status: str) -> str:
    """将 turn 状态映射为 run 状态字符串。

    参数:
        turn_status: ``turns.status`` 值。

    返回:
        对应 ``runs.status``；未知时 ``"running"``。
    """
    return TURN_TO_RUN_STATUS.get(turn_status, "running")


def extract_termination_reason(
    *,
    turn_status: str,
    terminal_event_type: str | None,
    payload: dict | None,
) -> str | None:
    """从终态 turn 与事件推断 ``runs.termination_reason``。

    参数:
        turn_status: 投影后的 turn 状态。
        terminal_event_type: 终态事件 type（如 ``turn.failed``）。
        payload: 终态事件 payload。

    返回:
        终止原因字符串；非终态 turn 时为 None。
    """
    if turn_status not in {"completed", "failed", "cancelled"}:
        return None
    if payload and payload.get("termination_reason"):
        return str(payload["termination_reason"])
    if terminal_event_type == "turn.failed":
        return str(payload.get("termination_reason", "fatal_error")) if payload else "fatal_error"
    if terminal_event_type == "turn.cancelled":
        return "cancelled"
    if turn_status == "completed":
        return "final"
    return None
