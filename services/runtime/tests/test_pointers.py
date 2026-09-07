from __future__ import annotations

from app.context.pointers import pointerize_stale_tool_results
from app.engine.state import assistant_tool_uses, tool_result_message, user_message


def test_pointerize_replaces_stale_grep_keeps_latest_read() -> None:
    grep_body = '{"matches": ["x"], "pattern": "foo"}' + ("y" * 400)
    read_body = "line\n" * 50
    messages = [
        user_message("hi"),
        assistant_tool_uses([{"id": "g1", "name": "grep", "input": {"pattern": "foo"}}]),
        tool_result_message("g1", grep_body),
        assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "a.py"}}]),
        tool_result_message("r1", read_body),
    ]
    out, n = pointerize_stale_tool_results(messages)
    assert n == 1
    grep_text = out[2]["content"][0]["content"]
    assert "_pointer" in grep_text
    read_text = out[4]["content"][0]["content"]
    assert read_text == read_body


def test_pointerize_keeps_latest_read_per_path() -> None:
    old_a = '{"path": "a.py", "content": "' + ("A" * 250) + '"}'
    new_a = '{"path": "a.py", "content": "' + ("B" * 250) + '"}'
    b_body = '{"path": "b.py", "content": "' + ("C" * 250) + '"}'
    messages = [
        user_message("hi"),
        assistant_tool_uses([{"id": "r1", "name": "read_file", "input": {"path": "a.py"}}]),
        tool_result_message("r1", old_a),
        assistant_tool_uses([{"id": "r2", "name": "read_file", "input": {"path": "b.py"}}]),
        tool_result_message("r2", b_body),
        assistant_tool_uses([{"id": "r3", "name": "read_file", "input": {"path": "a.py"}}]),
        tool_result_message("r3", new_a),
    ]
    out, n = pointerize_stale_tool_results(messages)
    assert n == 1
    assert "_pointer" in out[2]["content"][0]["content"]
    assert out[4]["content"][0]["content"] == b_body
    assert out[6]["content"][0]["content"] == new_a
