from __future__ import annotations

import json
from uuid import uuid4

from app.context.engine import ContextEngine, _summarize_messages
from app.context.policy import CompactionPolicy
from app.engine.state import TurnState, Usage, assistant_text, user_message


def test_context_engine_truncates_large_tool_results() -> None:
    from app.engine.state import assistant_tool_uses, tool_result_message

    engine = ContextEngine(token_budget=500)
    long_text = "x" * 10_000
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[
            user_message("hi"),
            assistant_tool_uses([{"id": "t1", "name": "read_file", "input": {"path": "a.md"}}]),
            tool_result_message("t1", long_text),
        ],
        usage=Usage(),
    )

    assembled = engine.assemble(system_prompt="sys", state=state)
    blob = str(assembled)
    assert engine.last_compaction_trace
    assert "budget_truncated" in blob or "autocompact" in blob or "collapsed" in blob


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
    summary = assembled[-1]["content"][0]["text"]
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


def test_estimate_window_breakdown_splits_categories() -> None:
    from app.context.engine import estimate_window_breakdown
    from app.engine.state import assistant_text, assistant_tool_uses, tool_result_message

    messages = [
        {"role": "system", "content": [{"type": "text", "text": "system rules"}]},
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
    assert breakdown["tools"] > 0
    assert breakdown["session"] > 0
    assert breakdown["user"] > 0
    assert breakdown["tool_results"] > 0
    assert breakdown["assistant"] > 0
