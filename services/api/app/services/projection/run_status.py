from __future__ import annotations

TURN_TO_RUN_STATUS: dict[str, str] = {
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "waiting_approval": "interrupted",
    "pending": "accepted",
    "running": "running",
}


def map_turn_to_run_status(turn_status: str) -> str:
    return TURN_TO_RUN_STATUS.get(turn_status, "running")


def extract_termination_reason(
    *,
    turn_status: str,
    terminal_event_type: str | None,
    payload: dict | None,
) -> str | None:
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
