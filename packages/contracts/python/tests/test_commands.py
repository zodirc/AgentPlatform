from __future__ import annotations

from uuid import uuid4

import pytest

from agent_contracts import ApproveToolCallCommand, StartTurnCommand


def test_start_turn_command_validates() -> None:
    cmd = StartTurnCommand(
        turn_id=uuid4(),
        run_id=uuid4(),
        session_id=uuid4(),
        scenario_id="writing",
        message="hello",
        trace_id=uuid4(),
    )
    assert cmd.scenario_id == "writing"
    assert cmd.plan_phase is None


def test_start_turn_command_accepts_tenant_scope() -> None:
    cmd = StartTurnCommand(
        turn_id=uuid4(),
        run_id=uuid4(),
        session_id=uuid4(),
        scenario_id="writing",
        message="hello",
        trace_id=uuid4(),
        work_id=uuid4(),
        work_root="/data/works/x",
        owner_user_id=uuid4(),
    )
    assert cmd.work_root == "/data/works/x"


def test_start_turn_command_rejects_invalid_plan_phase() -> None:
    with pytest.raises(Exception):
        StartTurnCommand(
            turn_id=uuid4(),
            run_id=uuid4(),
            session_id=uuid4(),
            scenario_id="agent",
            message="x",
            trace_id=uuid4(),
            plan_phase="ready",  # type: ignore[arg-type]
        )


def test_approve_tool_call_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        ApproveToolCallCommand(
            turn_id=uuid4(),
            run_id=uuid4(),
            tool_call_id="t1",
            trace_id=uuid4(),
            extra="nope",  # type: ignore[call-arg]
        )
