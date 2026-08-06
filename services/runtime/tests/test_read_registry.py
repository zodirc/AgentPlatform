"""docs/34 RC1–RC5 — read registry hard-gate, overlap, fold helpers."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.context.engine import ContextEngine, _fold_stale_read_file_results
from app.engine.read_registry import (
    PathReadState,
    deny_read_after_complete,
    deny_redundant_read,
    deserialize_read_registry,
    is_mutating_file_tool_failure,
    note_edit_failure_allows_reread,
    record_successful_read,
    serialize_read_registry,
)
from app.engine.state import TurnState, assistant_tool_use, tool_result_message
from app.tools.core import tools as core


def test_user_facing_policy_summary() -> None:
    from app.engine.read_registry import user_facing_policy_summary

    s = user_facing_policy_summary("read_after_complete", path="a.html")
    assert "已跳过" in s
    assert "a.html" in s
    assert "edit_file" in s
    b = user_facing_policy_summary("read_budget", budget=16)
    assert "16" in b


def test_deny_after_whole_file_complete() -> None:
    registry: dict[str, PathReadState] = {}
    record_successful_read(
        registry,
        path="a.html",
        offset=1,
        end_line=10,
        truncated=False,
        next_offset=None,
        whole_file_complete=True,
    )
    msg = deny_redundant_read(registry, path="./a.html", offset=100)
    assert msg is not None
    assert "read_after_complete" in msg


def test_deny_overlapping_covered_offset() -> None:
    registry: dict[str, PathReadState] = {}
    record_successful_read(
        registry,
        path="x.html",
        offset=1,
        end_line=100,
        truncated=True,
        next_offset=101,
        whole_file_complete=False,
    )
    assert deny_redundant_read(registry, path="x.html", offset=101) is None
    overlap = deny_redundant_read(registry, path="x.html", offset=50)
    assert overlap is not None
    assert "read_overlap" in overlap


def test_allow_next_offset_continuation() -> None:
    registry: dict[str, PathReadState] = {}
    record_successful_read(
        registry,
        path="big.txt",
        offset=1,
        end_line=50,
        truncated=True,
        next_offset=51,
        whole_file_complete=False,
    )
    assert deny_redundant_read(registry, path="big.txt", offset=51) is None
    assert deny_redundant_read(registry, path="big.txt", offset=200) is None


def test_edit_failure_allows_one_reread() -> None:
    registry: dict[str, PathReadState] = {}
    record_successful_read(
        registry,
        path="x.py",
        offset=1,
        end_line=5,
        truncated=False,
        next_offset=None,
        whole_file_complete=True,
    )
    assert deny_read_after_complete(registry, path="x.py", offset=1) is not None
    note_edit_failure_allows_reread(registry, path="x.py")
    assert deny_redundant_read(registry, path="x.py", offset=1) is None
    record_successful_read(
        registry,
        path="x.py",
        offset=1,
        end_line=5,
        truncated=False,
        next_offset=None,
        whole_file_complete=True,
    )
    assert deny_redundant_read(registry, path="x.py", offset=1) is not None


def test_registry_roundtrip() -> None:
    registry: dict[str, PathReadState] = {}
    record_successful_read(
        registry,
        path="f.txt",
        offset=1,
        end_line=3,
        truncated=False,
        next_offset=None,
        whole_file_complete=True,
    )
    raw = serialize_read_registry(registry)
    restored = deserialize_read_registry(raw)
    assert restored["f.txt"].whole_file_complete is True
    assert deny_redundant_read(restored, path="f.txt", offset=2) is not None


def test_mutating_failure_detection() -> None:
    assert is_mutating_file_tool_failure("edit_file", {"error": "old_text not found"})
    assert not is_mutating_file_tool_failure("edit_file", {"status": "edited"})
    assert not is_mutating_file_tool_failure("read_file", {"error": "x"})


def test_turn_state_default_registry() -> None:
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
    )
    assert state.read_registry == {}


@pytest.mark.asyncio
async def test_read_file_eof_from_offset_not_whole_complete(workspace: Path) -> None:
    body = "\n".join(f"L{i}" for i in range(1, 11))
    (workspace / "t.txt").write_text(body + "\n", encoding="utf-8")
    tail = await core.read_file("t.txt", offset=4)
    assert tail["truncated"] is False
    assert tail["whole_file_complete"] is False
    assert "eof_from_offset" in tail["summary"]


def test_fold_stale_read_file_results_keeps_latest() -> None:
    big = "x" * 500
    payload1 = json.dumps(
        {
            "path": "a.html",
            "offset": 1,
            "end_line": 10,
            "total_lines": 10,
            "content": big,
            "summary": "first",
            "whole_file_complete": True,
        },
        ensure_ascii=False,
    )
    payload2 = json.dumps(
        {
            "path": "a.html",
            "offset": 1,
            "end_line": 10,
            "total_lines": 10,
            "content": big + "y",
            "summary": "second",
            "whole_file_complete": True,
        },
        ensure_ascii=False,
    )
    messages = [
        assistant_tool_use("r1", "read_file", {"path": "a.html"}),
        tool_result_message("r1", payload1),
        assistant_tool_use("r2", "read_file", {"path": "a.html"}),
        tool_result_message("r2", payload2),
    ]
    out, folded, _paths = _fold_stale_read_file_results(messages, keep_last_per_path=1)
    assert folded == 1
    first_body = out[1]["content"][0]["content"]
    second_body = out[3]["content"][0]["content"]
    assert "_folded_read" in first_body or "[omitted" in first_body
    assert big + "y" in second_body


def test_assemble_trace_includes_read_fold() -> None:
    big = "z" * 600
    payload_a = json.dumps(
        {
            "path": "b.py",
            "offset": 1,
            "end_line": 20,
            "total_lines": 20,
            "content": big,
            "summary": "a",
            "whole_file_complete": True,
        },
        ensure_ascii=False,
    )
    payload_b = json.dumps(
        {
            "path": "b.py",
            "offset": 1,
            "end_line": 20,
            "total_lines": 20,
            "content": big + "2",
            "summary": "b",
            "whole_file_complete": True,
        },
        ensure_ascii=False,
    )
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            assistant_tool_use("r1", "read_file", {"path": "b.py"}),
            tool_result_message("r1", payload_a),
            assistant_tool_use("r2", "read_file", {"path": "b.py"}),
            tool_result_message("r2", payload_b),
        ],
    )
    engine = ContextEngine()
    engine.assemble(system_prompt="sys", state=state, tools=[])
    strategies = [t.get("strategy") for t in engine.last_compaction_trace]
    assert "read_fold" in strategies
