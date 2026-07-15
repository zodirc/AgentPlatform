from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.model.anthropic_provider import AnthropicProvider
from app.model.gateway import ModelResponse, StreamActivity
from app.model.openai_provider import OpenAIProvider


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeStreamCM:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    @asynccontextmanager
    async def stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[_FakeStreamResponse]:
        yield self._response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _collect(chunks: list[Any]) -> tuple[str, list[dict[str, Any]], int]:
    text = ""
    tool_calls: list[dict[str, Any]] = []
    output_tokens = 0
    for chunk in chunks:
        if isinstance(chunk, str):
            text += chunk
        elif isinstance(chunk, ModelResponse):
            if chunk.text and not text:
                text = chunk.text
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            output_tokens = chunk.output_tokens
    return text, tool_calls, output_tokens


@pytest.mark.asyncio
async def test_anthropic_provider_streams_text() -> None:
    lines = [
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":3}}',
    ]
    provider = AnthropicProvider(api_key="k", model_name="claude-test")

    with patch("app.model.anthropic_provider.httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(lines))):
        chunks = [c async for c in provider.stream(messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}], tools=[])]

    text, tool_calls, output_tokens = _collect(chunks)
    assert text == "Hello"
    assert tool_calls == []
    assert output_tokens == 3


@pytest.mark.asyncio
async def test_anthropic_provider_streams_tool_call() -> None:
    lines = [
        'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"tu1","name":"read_file"}}',
        'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"path\\": \\"a.md\\"}"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":7}}',
    ]
    provider = AnthropicProvider(api_key="k", model_name="claude-test")
    tools = [{"name": "read_file", "description": "read", "input_schema": {"type": "object", "properties": {}}}]

    with patch("app.model.anthropic_provider.httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(lines))):
        chunks = [c async for c in provider.stream(messages=[{"role": "user", "content": [{"type": "text", "text": "read"}]}], tools=tools)]

    _text, tool_calls, output_tokens = _collect(chunks)
    assert tool_calls
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["input"] == {"path": "a.md"}
    assert output_tokens == 7


@pytest.mark.asyncio
async def test_openai_provider_streams_text() -> None:
    lines = [
        f"data: {json.dumps({'choices': [{'delta': {'content': 'Hi'}}]})}",
        "data: [DONE]",
    ]
    provider = OpenAIProvider(api_key="k", model_name="gpt-test")

    with patch("app.model.openai_provider.httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(lines))):
        chunks = [c async for c in provider.stream(messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}], tools=[])]

    text, tool_calls, _ = _collect(chunks)
    assert text == "Hi"
    assert tool_calls == []
    assert any(isinstance(c, StreamActivity) for c in chunks)


@pytest.mark.asyncio
async def test_openai_provider_signals_activity_on_reasoning_before_content() -> None:
    """DeepSeek-style: long reasoning with content=null must still unblock first-byte."""
    lines = [
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "",
                        }
                    }
                ]
            }
        ),
        "data: "
        + json.dumps(
            {"choices": [{"delta": {"content": None, "reasoning_content": "用户"}}]}
        ),
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "function": {"name": "read_file", "arguments": "{"},
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '"path":"a.md"}'},
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        "data: [DONE]",
    ]
    provider = OpenAIProvider(api_key="k", model_name="deepseek-v4-flash")
    tools = [
        {
            "name": "read_file",
            "description": "read",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    with patch(
        "app.model.openai_provider.httpx.AsyncClient",
        return_value=_FakeAsyncClient(_FakeStreamResponse(lines)),
    ):
        chunks = [
            c
            async for c in provider.stream(
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "read"}],
                    }
                ],
                tools=tools,
            )
        ]

    assert isinstance(chunks[0], StreamActivity)
    assert sum(1 for c in chunks if isinstance(c, StreamActivity)) == 1
    _text, tool_calls, _ = _collect(chunks)
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["input"] == {"path": "a.md"}


@pytest.mark.asyncio
async def test_openai_provider_streams_tool_call() -> None:
    chunk1 = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {"index": 0, "id": "call-1", "function": {"name": "read_file", "arguments": "{"}}
                    ]
                }
            }
        ]
    }
    chunk2 = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": '"path":"x.md"}'}}]
                }
            }
        ]
    }
    lines = [
        f"data: {json.dumps(chunk1)}",
        f"data: {json.dumps(chunk2)}",
        "data: [DONE]",
    ]
    provider = OpenAIProvider(api_key="k", model_name="gpt-test")
    tools = [{"name": "read_file", "description": "read", "input_schema": {"type": "object", "properties": {}}}]

    with patch("app.model.openai_provider.httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(lines))):
        chunks = [c async for c in provider.stream(messages=[{"role": "user", "content": [{"type": "text", "text": "read"}]}], tools=tools)]

    _text, tool_calls, _ = _collect(chunks)
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["input"] == {"path": "x.md"}
