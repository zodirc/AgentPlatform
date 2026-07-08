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


def test_approve_tool_call_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        ApproveToolCallCommand(
            turn_id=uuid4(),
            run_id=uuid4(),
            tool_call_id="t1",
            trace_id=uuid4(),
            extra="nope",  # type: ignore[call-arg]
        )
