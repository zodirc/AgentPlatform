from __future__ import annotations

from uuid import uuid4

from app.controller.checkpoint_store import _deserialize_state, _serialize_state
from app.engine.read_registry import PathReadState
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
        exec_preapproved=True,
        read_registry={
            "a.py": PathReadState(whole_file_complete=True, covered_ranges=[(1, 10)]),
        },
    )
    raw = _serialize_state(state)
    assert "李云龙" in raw["volatile_context"]
    assert raw["read_registry"]["a.py"]["whole_file_complete"] is True
    assert raw["exec_preapproved"] is True
    restored = _deserialize_state(raw)
    assert restored.volatile_context == state.volatile_context
    assert restored.plan_phase == "executing"
    assert restored.writes_preapproved is True
    assert restored.exec_preapproved is True
    assert restored.read_registry["a.py"].whole_file_complete is True


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
    assert restored.read_registry == {}


def test_wants_run_tests_requires_marker() -> None:
    assert _wants_run_tests("[test] run project tests") is True
    assert _wants_run_tests("agent.11 please verify") is True
    assert _wants_run_tests("please call run_tests then patch") is False
