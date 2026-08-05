from __future__ import annotations

import json
from uuid import uuid4

from app.context.engine import ContextEngine, _summarize_messages
from app.context.policy import CompactionPolicy
from app.engine.state import TurnState, Usage, assistant_text, user_message


def test_context_engine_truncates_large_tool_results() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message

    engine = ContextEngine(token_budget=500)
    # Non-read tools still use the default 4k budget (C-1).
    long_text = "x" * 10_000
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[
            user_message("hi"),
            assistant_tool_uses([{"id": "t1", "name": "list_dir", "input": {"path": "."}}]),
            tool_result_message("t1", long_text),
        ],
        usage=Usage(),
    )

    assembled = engine.assemble(system_prompt="sys", state=state)
    blob = str(assembled)
    assert engine.last_compaction_trace
    assert "budget_truncated" in blob or "autocompact" in blob or "collapsed" in blob


def test_latest_read_file_keeps_large_body() -> None:
    """C-1: latest read_file uses higher char budget (default 32k), not 4k."""
    from app.context.engine import _apply_tool_result_budget
    from app.engine.state import assistant_tool_uses, tool_result_message

    body = "ANSWER_NEAR_END_" + ("y" * 12_000) + "_TAIL"
    messages = [
        user_message("q"),
        assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "p.md"}}]),
        tool_result_message("r1", body),
    ]
    out, truncated = _apply_tool_result_budget(messages, preserve_short=True)
    text = out[-1]["content"][0]["content"]
    assert truncated == 0
    assert "ANSWER_NEAR_END_" in text
    assert "_TAIL" in text
    assert "[budget_truncated]" not in text


def test_stale_read_still_budgeted_after_fold() -> None:
    """C-1: after read_fold, only the latest path body is large; older are stubs."""
    from app.engine.state import assistant_tool_uses, tool_result_message

    engine = ContextEngine(token_budget=200_000)
    pad_a = json.dumps({"content": "A" * 8_000, "path": "a.md"}, ensure_ascii=False)
    pad_b = json.dumps({"content": "B" * 8_000, "path": "a.md"}, ensure_ascii=False)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("read twice"),
            assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "a.md"}}]),
            tool_result_message("r1", pad_a),
            assistant_tool_uses([{"id": "r2", "name": "read_file", "input": {"path": "a.md"}}]),
            tool_result_message("r2", pad_b),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    blob = str(assembled)
    assert "BBBB" in blob or "B" * 100 in blob
    strategies = [e.get("strategy") for e in engine.last_compaction_trace]
    assert "read_fold" in strategies


def test_snip_floor_keeps_latest_read_and_instruction() -> None:
    """C-1: snip must not drop the current user turn or latest read_file cycle."""
    from app.context.engine import _pop_oldest_message_group, _protected_tail_start
    from app.engine.state import assistant_tool_uses, tool_result_message

    marker = "PROTECTED_READ_BODY_" + ("z" * 200)
    messages = [
        user_message("old task one"),
        assistant_tool_uses([{"id": "o1", "name": "list_dir", "input": {"path": "."}}]),
        tool_result_message("o1", '{"entries":[]}'),
        user_message("old task two"),
        assistant_tool_uses([{"id": "o2", "name": "list_dir", "input": {"path": "."}}]),
        tool_result_message("o2", '{"entries":[]}'),
        user_message("CURRENT_INSTRUCTION_MARKER"),
        assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "big.md"}}]),
        tool_result_message("r1", marker),
    ]
    protect = _protected_tail_start(messages)
    assert protect > 0
    # Exhaust unprotected prefix via snip floor.
    while _pop_oldest_message_group(messages, protect_from=_protected_tail_start(messages)):
        pass
    blob = str(messages)
    assert "CURRENT_INSTRUCTION_MARKER" in blob
    assert "PROTECTED_READ_BODY_" in blob

    # Assemble with autocompact disabled so snip floor is the path under test.
    policy = CompactionPolicy(
        model_window_tokens=400,
        output_reserve_tokens=50,
        fill_collapse=0.5,
        fill_snip=0.55,
        fill_autocompact=1.01,
        hot_zone_ratio=0.35,
    )
    engine = ContextEngine(policy=policy)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("old task one"),
            assistant_tool_uses([{"id": "o1", "name": "list_dir", "input": {"path": "."}}]),
            tool_result_message("o1", '{"entries":[]}'),
            user_message("old task two"),
            assistant_tool_uses([{"id": "o2", "name": "list_dir", "input": {"path": "."}}]),
            tool_result_message("o2", '{"entries":[]}'),
            user_message("CURRENT_INSTRUCTION_MARKER"),
            assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "big.md"}}]),
            tool_result_message("r1", marker),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    blob2 = str(assembled)
    assert "CURRENT_INSTRUCTION_MARKER" in blob2
    assert "PROTECTED_READ_BODY_" in blob2


def test_summarize_messages_extracts_snippets() -> None:
    summary = _summarize_messages(
        [
            user_message("outline the document"),
            assistant_text("here is a detailed outline"),
            user_message("expand section two"),
        ]
    )["content"][0]["text"]
    assert "autocompact" in summary
    assert "section two" in summary or "outline" in summary


def test_context_engine_autocompact_includes_message_snippets() -> None:
    engine = ContextEngine(token_budget=12)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[
            user_message("first question about outline"),
            assistant_text("first answer with details"),
            user_message("follow up about section two"),
            assistant_text("second answer"),
            user_message("third question"),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    # Mutable runtime trails the transcript; autocompact summary is in messages body.
    assert assembled[-1]["content"][0]["text"].startswith("[runtime_context]")
    summary = next(
        m["content"][0]["text"]
        for m in assembled
        if m.get("role") == "user"
        and "autocompact" in str(m.get("content", [{}])[0].get("text", ""))
    )
    assert "autocompact" in summary
    assert any(entry.get("strategy") == "compact" for entry in engine.last_compaction_trace)


def test_context_engine_microcompacts_consecutive_tool_results() -> None:
    engine = ContextEngine(token_budget=50_000)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[
            user_message("hi"),
            {
                "role": "tool",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a"}],
            },
            {
                "role": "tool",
                "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "b"}],
            },
        ],
        usage=Usage(),
    )
    engine.assemble(system_prompt="sys", state=state)
    strategies = [entry.get("strategy") for entry in engine.last_compaction_trace]
    assert "microcompact" in strategies


def test_context_engine_preserves_tool_results_after_assistant_tool_use() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message

    engine = ContextEngine(token_budget=50_000)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("create docs"),
            assistant_tool_uses(
                [
                    {"id": "call-1", "name": "read_file", "input": {"path": "README.md"}},
                    {"id": "call-2", "name": "list_dir", "input": {"path": "."}},
                ],
                text="checking workspace",
            ),
            tool_result_message("call-1", '{"content": "hello"}'),
            tool_result_message("call-2", '{"entries": []}'),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    roles = [m["role"] for m in assembled if m["role"] != "system"]
    assert roles.count("tool") == 2
    assert "microcompact" not in [entry.get("strategy") for entry in engine.last_compaction_trace]


def test_context_engine_snip_does_not_leave_orphan_tools() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message
    from app.model.openai_messages import _to_openai_messages

    engine = ContextEngine(token_budget=80)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("old task"),
            assistant_tool_uses(
                [{"id": "old-1", "name": "list_dir", "input": {"path": "."}}],
                text="old",
            ),
            tool_result_message("old-1", "{}"),
            user_message("补充世界杯文档"),
            assistant_tool_uses(
                [
                    {"id": "call-1", "name": "read_file", "input": {"path": "doc.md"}},
                    {"id": "call-2", "name": "grep", "input": {"pattern": "球队"}},
                ],
                text="reading",
            ),
            tool_result_message("call-1", '{"content": "doc"}'),
            tool_result_message("call-2", '{"matches": []}'),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    converted = _to_openai_messages([m for m in assembled if m.get("role") != "system"])
    for index, message in enumerate(converted):
        if message.get("role") == "tool":
            prev = converted[index - 1] if index > 0 else None
            assert prev and prev.get("role") == "assistant" and prev.get("tool_calls")


def test_context_engine_preserves_short_list_dir_microcompact() -> None:
    from app.engine.state import tool_result_message

    list_dir_body = json.dumps({"path": ".", "entries": ["a.md", "b/"]})
    engine = ContextEngine(token_budget=50_000)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("explore"),
            tool_result_message("t1", list_dir_body),
            tool_result_message("t2", list_dir_body),
            tool_result_message("t3", list_dir_body),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    tool_msgs = [m for m in assembled if m.get("role") == "tool"]
    assert len(tool_msgs) == 3
    assert "microcompact" not in [e.get("strategy") for e in engine.last_compaction_trace]


def test_context_engine_does_not_truncate_short_list_dir() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message

    list_dir_body = json.dumps({"path": ".", "entries": ["README.md"]})
    engine = ContextEngine(token_budget=500)
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("hi"),
            assistant_tool_uses([{"id": "t1", "name": "list_dir", "input": {"path": "."}}]),
            tool_result_message("t1", list_dir_body),
        ],
        usage=Usage(),
    )
    assembled = engine.assemble(system_prompt="sys", state=state)
    tool_text = str(assembled)
    assert "README.md" in tool_text
    assert "budget_truncated" not in tool_text


def test_estimate_assembled_window_includes_system_and_tools() -> None:
    from app.context.engine import estimate_assembled_window

    messages = [
        {"role": "system", "content": [{"type": "text", "text": "x" * 400}]},
        {"role": "user", "content": [{"type": "text", "text": "你好"}]},
    ]
    tools = [{"name": "list_dir", "description": "list files", "input_schema": {"type": "object"}}]
    window = estimate_assembled_window(messages=messages, tools=tools)
    assert window["system_tokens"] > 50
    assert window["tools_tokens"] > 10
    assert window["messages_tokens"] >= 1
    assert window["tokens_after"] == (
        window["system_tokens"] + window["tools_tokens"] + window["messages_tokens"]
    )
    # Saying hi alone must NOT dominate — tools+system should be most of the window.
    assert window["messages_tokens"] < window["tokens_after"] // 2


def test_context_engine_collapse_triggered_by_fill_ratio() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message

    policy = CompactionPolicy(
        model_window_tokens=800,
        output_reserve_tokens=64,
        fill_collapse=0.5,
        fill_snip=0.95,
        fill_autocompact=0.99,
        hot_zone_ratio=0.3,
    )
    engine = ContextEngine(policy=policy)
    long_tool = "y" * 3000
    messages = [user_message("start")]
    for index in range(6):
        tool_id = f"t{index}"
        messages.append(
            assistant_tool_uses(
                [{"id": tool_id, "name": "read_file", "input": {"path": f"f{index}.md"}}],
                text=f"step {index}",
            )
        )
        messages.append(tool_result_message(tool_id, long_tool))

    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=messages,
        usage=Usage(),
    )
    engine.assemble(system_prompt="sys", state=state, tools=[])
    strategies = [entry.get("strategy") for entry in engine.last_compaction_trace]
    assert "collapse" in strategies


def test_collapse_pointer_includes_dropped_tools() -> None:
    from app.context.engine import _collapse_tool_history
    from app.engine.state import assistant_tool_uses, tool_result_message

    policy = CompactionPolicy(
        model_window_tokens=2_000,
        output_reserve_tokens=64,
        fill_collapse=0.01,
        fill_snip=0.99,
        fill_autocompact=0.995,
        hot_zone_ratio=0.2,
    )
    list_body = json.dumps({"path": "exports", "entries": ["a.md", "b.cpp", "c.log"]})
    pad = "z" * 800
    messages = [user_message("explore")]
    for index in range(4):
        list_id = f"list-{index}"
        read_id = f"read-{index}"
        messages.append(
            assistant_tool_uses(
                [
                    {"id": list_id, "name": "list_dir", "input": {"path": "exports"}},
                    {"id": read_id, "name": "read_file", "input": {"path": f"f{index}.md"}},
                ],
                text=f"step {index}",
            )
        )
        messages.append(tool_result_message(list_id, list_body))
        messages.append(tool_result_message(read_id, pad))
    messages.append(user_message("continue"))
    messages.append(assistant_text("done"))

    out = _collapse_tool_history(
        messages,
        [],
        system_prompt="sys",
        tools=None,
        policy=policy,
    )
    pointer = next(
        (
            block.get("text", "")
            for msg in out
            for block in msg.get("content", [])
            if isinstance(block, dict) and "collapsed" in str(block.get("text", ""))
        ),
        "",
    )
    assert "dropped tools:" in pointer
    assert "list_dir×" in pointer
    assert "read_file×" in pointer
    assert "a.md" in pointer
    assert "pinned tool results preserved:" in pointer


def test_estimate_window_breakdown_splits_categories() -> None:
    from app.context.engine import estimate_window_breakdown
    from app.engine.state import assistant_text, assistant_tool_uses, tool_result_message

    messages = [
        {"role": "system", "content": [{"type": "text", "text": "system rules"}]},
        {
            "role": "user",
            "content": [{"type": "text", "text": "[project_context]\n## AGENT.md\nhi"}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[Session context] Previous turn ended with status=completed.",
                }
            ],
        },
        user_message("read file"),
        assistant_tool_uses([{"id": "t1", "name": "read_file", "input": {"path": "a.md"}}]),
        tool_result_message("t1", '{"content": "hello"}'),
        assistant_text("done"),
    ]
    tools = [{"name": "read_file", "description": "read", "input_schema": {}}]
    breakdown = estimate_window_breakdown(messages=messages, tools=tools)
    assert breakdown["system"] > 0
    assert breakdown["project"] > 0
    assert breakdown["tools"] > 0
    assert breakdown["session"] > 0
    assert breakdown["user"] > 0
    assert breakdown["tool_results"] > 0
    assert breakdown["assistant"] > 0


def test_apply_tool_result_budget_preserves_writing_section_extract() -> None:
    from app.context.engine import _apply_tool_result_budget

    payload = json.dumps(
        {
            "writing_section_extract": True,
            "content": "X" * 9000,
            "path": "manuscript.md",
            "section_id": "ch1",
        },
        ensure_ascii=False,
    )
    messages = [
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": payload}],
        }
    ]
    out, truncated = _apply_tool_result_budget(messages, 4000)
    assert truncated == 0
    assert "X" * 100 in out[0]["content"][0]["content"]
    assert "budget_truncated" not in out[0]["content"][0]["content"]


def test_protected_tail_and_latest_read_budget_edges() -> None:
    from app.context.engine import (
        _apply_tool_result_budget,
        _budget_limits,
        _protected_tail_start,
    )
    from app.engine.state import assistant_tool_uses, tool_result_message, user_message
    from unittest.mock import patch

    # Explicit latest_read_budget override.
    huge = "y" * 10_000
    messages = [
        user_message("q"),
        assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "a"}}]),
        tool_result_message("r1", huge),
        {
            "role": "tool",
            "content": [{"type": "text", "text": "noise"}],
        },
    ]
    out, n = _apply_tool_result_budget(
        messages, char_budget=100, latest_read_budget=50_000
    )
    assert n == 0
    assert out[2]["content"][0]["content"] == huge

    # Protect floor: tail starts at latest read cycle / last user.
    start = _protected_tail_start(messages)
    assert start >= 0
    assert start <= 1

    # Orphan tool result (no preceding tool_use) still protects at that index.
    orphan = [
        user_message("q"),
        tool_result_message("orphan", "data"),
    ]
    # Force name map to treat orphan as read_file via patched helper.
    with patch(
        "app.context.engine._tool_use_name_by_id",
        return_value={"orphan": "read_file"},
    ):
        assert _protected_tail_start(orphan) >= 0

    with patch("app.context.engine._budget_limits", return_value=(4000, 32000, False)):
        assert _protected_tail_start(messages) == 0

    # Empty messages + protect off path via monkeypatch.
    limits = _budget_limits()
    assert limits[0] > 0
    assert _protected_tail_start([]) == 0


def test_assemble_ms_large_latest_read_stays_bounded() -> None:
    """C-1 R5: large latest read_file must assemble without pathological delay."""
    from app.engine.state import assistant_tool_uses, tool_result_message

    body = ("ANSWER_MARKER_" + ("z" * 28_000) + "_END")
    policy = CompactionPolicy(
        model_window_tokens=200_000,
        output_reserve_tokens=4_000,
        fill_collapse=0.95,
        fill_snip=0.97,
        fill_autocompact=1.01,
        hot_zone_ratio=0.35,
    )
    times: list[float] = []
    for _ in range(5):
        engine = ContextEngine(policy=policy)
        state = TurnState(
            turn_id=uuid4(),
            session_id=uuid4(),
            run_id=uuid4(),
            trace_id=uuid4(),
            scenario_id="agent",
            messages=[
                user_message("read the long file and answer"),
                assistant_tool_uses(
                    [{"id": "r1", "name": "read_file", "input": {"path": "big.md"}}]
                ),
                tool_result_message("r1", body),
            ],
            usage=Usage(),
        )
        assembled = engine.assemble(system_prompt="sys", state=state)
        blob = str(assembled)
        assert "ANSWER_MARKER_" in blob
        assert "_END" in blob
        times.append(float(engine.last_assemble_ms))
    assert all(t >= 0 for t in times)
    # Weak host guardrail: median under 250ms, max under 1s (string/budget only).
    times_sorted = sorted(times)
    median = times_sorted[len(times_sorted) // 2]
    assert median < 250.0, times
    assert max(times) < 1000.0, times
