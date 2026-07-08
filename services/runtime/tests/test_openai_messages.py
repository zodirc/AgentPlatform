from __future__ import annotations

from app.model.openai_messages import _to_openai_messages


def test_openai_messages_include_assistant_tool_use() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "run tool"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": '{"content": "hello"}',
                }
            ],
        },
    ]
    converted = _to_openai_messages(messages)
    assistant = converted[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] is None
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
def test_openai_messages_repair_missing_tool_results() -> None:
    broken = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "list_dir", "input": {"path": "."}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "[microcompact: folded 1 tool results]"}],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-2", "name": "read_file", "input": {"path": "a.md"}},
            ],
        },
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "call-2", "content": "{}"}],
        },
    ]
    converted = _to_openai_messages(broken)
    assert converted[2]["role"] == "tool"
    assert converted[2]["tool_call_id"] == "call-1"


def test_openai_messages_drop_orphan_tool_messages() -> None:
    broken = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "orphan-1", "content": "{}"}],
        },
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "orphan-2", "content": "{}"}],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {"path": "a.md"}},
            ],
        },
        {
            "role": "tool",
            "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "{}"}],
        },
    ]
    converted = _to_openai_messages(broken)
    assert converted[0]["role"] == "user"
    assert all(m.get("role") != "tool" or m.get("tool_call_id") == "call-1" for m in converted)
    assert converted[1]["role"] == "assistant"
    assert converted[2]["tool_call_id"] == "call-1"
