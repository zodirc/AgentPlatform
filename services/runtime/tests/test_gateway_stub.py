from __future__ import annotations

import pytest

from app.engine.state import assistant_tool_use, tool_result_message
from app.model.gateway import (
    StubModelProvider,
    _assistant_requested_verify_delegate,
    _delegate_tool_result_count,
    _tool_result_denied,
)


def test_delegate_tool_result_count_only_completed_cycles() -> None:
    messages = [
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "1",
                    "content": '{"subagent_id": "sub-a", "status": "completed"}',
                }
            ],
        },
        {"role": "assistant", "content": [{"type": "tool_use", "name": "delegate", "id": "2"}]},
    ]
    assert _delegate_tool_result_count(messages) == 1


def test_tool_result_denied_detects_status() -> None:
    messages = [
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": '{"status": "denied", "reason": "no"}',
                    "is_error": True,
                }
            ],
        },
    ]
    assert _tool_result_denied(messages) is True


def test_assistant_requested_verify_delegate() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "delegate",
                    "id": "d1",
                    "input": {"task": "verify", "agent_type": "verify"},
                }
            ],
        },
    ]
    assert _assistant_requested_verify_delegate(messages) is True


@pytest.mark.asyncio
async def test_stub_double_delegate_completes_with_engine_messages() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "agent.06 explore verify 串联"}]},
    ]
    messages.append(assistant_tool_use("delegate-aaa", "delegate", {"task": "x", "agent_type": "explore"}))
    messages.append(
        tool_result_message("delegate-aaa", '{"subagent_id": "sub-a", "status": "completed"}')
    )
    messages.append(assistant_tool_use("delegate-bbb", "delegate", {"task": "verify", "agent_type": "verify"}))
    messages.append(
        tool_result_message("delegate-bbb", '{"subagent_id": "sub-b", "status": "completed"}')
    )

    provider = StubModelProvider()
    chunks = [chunk async for chunk in provider.stream(messages=messages, tools=[{"name": "delegate"}])]
    text = "".join(c if isinstance(c, str) else c.text for c in chunks)
    assert "agent.06" in text


@pytest.mark.asyncio
async def test_stub_run_command_after_deny_completes() -> None:
    provider = StubModelProvider()
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "agent.09 deny run_command"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "run_command", "id": "c1"}],
        },
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": '{"status": "denied", "reason": "user_denied"}',
                    "is_error": True,
                }
            ],
        },
    ]
    chunks = [chunk async for chunk in provider.stream(messages=messages, tools=[{"name": "run_command"}])]
    text = "".join(c if isinstance(c, str) else c.text for c in chunks)
    assert "拒绝" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "你对我们的资料库有什么理解？",
        "资料库里有什么",
        "介绍一下 sources 目录",
    ],
)
async def test_stub_source_library_meta_question_does_not_search(message: str) -> None:
    provider = StubModelProvider()
    messages = [{"role": "user", "content": [{"type": "text", "text": message}]}]

    chunks = [
        chunk
        async for chunk in provider.stream(
            messages=messages,
            tools=[{"name": "search_sources"}, {"name": "read_file"}],
        )
    ]

    assert not any(
        call["name"] == "search_sources"
        for chunk in chunks
        if not isinstance(chunk, str)
        for call in (chunk.tool_calls or [])
    )


@pytest.mark.asyncio
async def test_stub_writing_05_explicit_citation_still_searches() -> None:
    provider = StubModelProvider()
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "writing.05：引用资料库内容写一节"}],
        }
    ]

    chunks = [
        chunk
        async for chunk in provider.stream(
            messages=messages,
            tools=[{"name": "search_sources"}],
        )
    ]

    tool_calls = [
        call
        for chunk in chunks
        if not isinstance(chunk, str)
        for call in (chunk.tool_calls or [])
    ]
    assert [call["name"] for call in tool_calls] == ["search_sources"]
