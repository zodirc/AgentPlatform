from __future__ import annotations

from app.engine.child_spawn import (
    park_spawned_child,
    should_spawn_child,
    splice_child_results,
)
from app.engine.state import assistant_tool_uses, tool_result_message, user_message
from app.tools.delegate_context import bump_delegate_depth, reset_delegate_depth


def test_should_spawn_at_parent_depth() -> None:
    assert should_spawn_child(agent_type="explore", wait=True) is True
    assert should_spawn_child(agent_type="edit", wait=True) is True
    assert should_spawn_child(agent_type="explore", wait=False) is False


def test_should_not_spawn_when_nested() -> None:
    token = bump_delegate_depth()
    try:
        assert should_spawn_child(agent_type="explore", wait=True) is False
    finally:
        reset_delegate_depth(token)


def test_splice_child_results_inserts_in_tool_use_order() -> None:
    messages = [
        user_message("hi"),
        assistant_tool_uses(
            [
                {"id": "c1", "name": "delegate", "input": {"task": "a"}},
                {"id": "w1", "name": "write_file", "input": {"path": "a"}},
            ]
        ),
        tool_result_message("w1", '{"status":"ok"}'),
    ]
    splice_child_results(
        messages,
        {"c1": {"status": "completed", "summary": "explored"}},
    )
    ids = [
        block.get("tool_use_id")
        for msg in messages
        if msg.get("role") == "tool"
        for block in msg.get("content") or []
        if block.get("type") == "tool_result"
    ]
    assert ids == ["c1", "w1"]


class _Engine:
    def __init__(self) -> None:
        self.pending_children: list[dict] = []


def test_park_spawned_child_queues_and_skips_plain_results() -> None:
    engine = _Engine()
    assert (
        park_spawned_child(
            engine,
            result={"status": "ok", "summary": "done"},
            tool_call_id="c1",
            step_index=2,
            arguments={"task": "调研", "agent_type": "researcher"},
            turn_id="t",
            run_id="r",
        )
        is False
    )
    assert engine.pending_children == []
    assert (
        park_spawned_child(
            engine,
            result={
                "status": "spawn_child",
                "child": {"task": "调研资料 writing.06", "agent_type": "researcher"},
            },
            tool_call_id="c1",
            step_index=2,
            arguments={"task": "调研", "agent_type": "explore"},
            turn_id="t",
            run_id="r",
        )
        is True
    )
    assert len(engine.pending_children) == 1
    spec = engine.pending_children[0]
    assert spec["tool_call_id"] == "c1"
    assert spec["agent_type"] == "researcher"
    assert spec["task"] == "调研资料 writing.06"
