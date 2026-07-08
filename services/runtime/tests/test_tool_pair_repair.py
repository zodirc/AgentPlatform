from __future__ import annotations

from uuid import uuid4

from app.context.engine import ContextEngine
from app.engine.state import TurnState, assistant_tool_uses, tool_result_message, user_message
from app.model.openai_messages import _to_openai_messages


def test_assemble_preserves_tool_pairs_for_multi_step_agent() -> None:
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="agent",
        messages=[
            user_message("create agent docs"),
            assistant_tool_uses(
                [{"id": "call_00_5Cqv", "name": "list_dir", "input": {"path": "."}}],
                text="checking",
            ),
            tool_result_message("call_00_5Cqv", '{"path": ".", "entries": ["README.md"]}'),
            assistant_tool_uses(
                [
                    {"id": "call_00_aIb", "name": "read_file", "input": {"path": "README.md"}},
                    {"id": "call_01_xKJZ", "name": "list_dir", "input": {"path": ".agent"}},
                ],
                text="reading",
            ),
            tool_result_message("call_00_aIb", '{"content": "# Agent"}'),
            tool_result_message("call_01_xKJZ", '{"entries": ["revisions/"]}'),
        ],
    )
    engine = ContextEngine()
    assembled = engine.assemble(system_prompt="sys", state=state)
    converted = _to_openai_messages([m for m in assembled if m.get("role") != "system"])

    for index, message in enumerate(converted):
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        expected_ids = [call["id"] for call in message["tool_calls"]]
        following = []
        cursor = index + 1
        while cursor < len(converted) and converted[cursor].get("role") == "tool":
            following.append(converted[cursor]["tool_call_id"])
            cursor += 1
        assert following == expected_ids, (expected_ids, following, converted)
