from __future__ import annotations

from app.services.projection.run_status import extract_termination_reason, map_turn_to_run_status


def test_map_turn_completed_to_run_succeeded() -> None:
    assert map_turn_to_run_status("completed") == "succeeded"


def test_map_turn_waiting_approval_to_interrupted() -> None:
    assert map_turn_to_run_status("waiting_approval") == "interrupted"


def test_extract_termination_reason_from_completed_payload() -> None:
    reason = extract_termination_reason(
        turn_status="completed",
        terminal_event_type="turn.completed",
        payload={"termination_reason": "max_steps", "summary": "done"},
    )
    assert reason == "max_steps"


def test_extract_termination_reason_defaults_to_final() -> None:
    reason = extract_termination_reason(
        turn_status="completed",
        terminal_event_type="turn.completed",
        payload={"summary": "done"},
    )
    assert reason == "final"
