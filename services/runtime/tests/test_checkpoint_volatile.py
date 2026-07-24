from __future__ import annotations

from uuid import uuid4

from app.controller.checkpoint_store import _deserialize_state, _serialize_state
from app.engine.state import TurnState
from app.model.gateway import StubModelProvider, _wants_run_tests


def test_checkpoint_roundtrip_preserves_volatile_context() -> None:
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        volatile_context="## Writing cards（必须遵守）\nrole: 李云龙\n",
        plan_phase="executing",
        writes_preapproved=True,
    )
    raw = _serialize_state(state)
    assert "李云龙" in raw["volatile_context"]
    restored = _deserialize_state(raw)
    assert restored.volatile_context == state.volatile_context
    assert restored.plan_phase == "executing"
    assert restored.writes_preapproved is True


def test_checkpoint_deserializes_legacy_without_volatile() -> None:
    """Old checkpoints omit volatile_context — must not crash."""
    data = {
        "turn_id": str(uuid4()),
        "session_id": str(uuid4()),
        "run_id": str(uuid4()),
        "trace_id": str(uuid4()),
        "scenario_id": "agent",
        "messages": [],
    }
    restored = _deserialize_state(data)
    assert restored.volatile_context == ""


def test_wants_run_tests_requires_marker() -> None:
    assert _wants_run_tests("[test] run project tests") is True
    assert _wants_run_tests("agent.11 please verify") is True
    assert _wants_run_tests("please call run_tests then patch") is False
