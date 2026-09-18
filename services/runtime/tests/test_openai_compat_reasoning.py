from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

from app.model.generation import (
    GenerationParams,
    apply_openai_compat_reasoning,
    apply_response_schema,
    openai_compat_model_family,
    repair_openai_compat_payload,
    strip_next_openai_compat_field,
)
from app.model.gateway import ModelResponse
from app.model.openai_provider import OpenAIProvider


def test_openai_compat_model_family() -> None:
    assert openai_compat_model_family("gpt-5.6-luna") == "gpt5"
    assert openai_compat_model_family("openai/gpt-5.6-luna") == "gpt5"
    assert openai_compat_model_family("deepseek-v4-flash") == "deepseek"
    assert openai_compat_model_family("gpt-4o") == "other"


def test_apply_openai_compat_reasoning_gpt5_defaults_high() -> None:
    payload: dict[str, Any] = {}
    apply_openai_compat_reasoning(
        payload,
        model_name="gpt-5.6-luna",
        gen=GenerationParams(),
    )
    assert payload == {"reasoning_effort": "high"}


def test_apply_openai_compat_reasoning_deepseek_thinking_and_effort() -> None:
    payload: dict[str, Any] = {}
    apply_openai_compat_reasoning(
        payload,
        model_name="deepseek-v4-flash",
        gen=GenerationParams(),
    )
    assert payload == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def test_apply_openai_compat_reasoning_none_omits() -> None:
    payload: dict[str, Any] = {}
    apply_openai_compat_reasoning(
        payload,
        model_name="gpt-5.6-luna",
        gen=GenerationParams(reasoning_effort="none"),
    )
    assert payload == {}


def test_apply_openai_compat_reasoning_none_disables_deepseek_thinking() -> None:
    payload: dict[str, Any] = {}
    apply_openai_compat_reasoning(
        payload,
        model_name="deepseek-v4-flash",
        gen=GenerationParams(reasoning_effort="none"),
    )
    assert payload == {"thinking": {"type": "disabled"}}


def test_repair_openai_compat_payload_disables_thinking_for_tool_choice() -> None:
    payload: dict[str, Any] = {
        "tool_choice": {"type": "function", "function": {"name": "book_candidate"}},
    }
    assert repair_openai_compat_payload(
        payload,
        body='{"error":{"message":"Thinking mode does not support this tool_choice"}}',
    )
    assert payload["thinking"] == {"type": "disabled"}
    assert (
        repair_openai_compat_payload(
            payload,
            body="Thinking mode does not support this tool_choice",
        )
        is False
    )


def test_apply_openai_compat_reasoning_skips_gpt4() -> None:
    payload: dict[str, Any] = {}
    apply_openai_compat_reasoning(
        payload, model_name="gpt-4o", gen=GenerationParams()
    )
    assert payload == {}


def test_strip_next_openai_compat_field_layers() -> None:
    payload = {
        "stream_options": {"include_usage": True},
        "reasoning_effort": "high",
        "thinking": {"type": "enabled"},
    }
    assert strip_next_openai_compat_field(payload) is True
    assert "stream_options" not in payload
    assert "reasoning_effort" in payload
    assert strip_next_openai_compat_field(payload) is True
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload
    assert strip_next_openai_compat_field(payload) is False


def test_apply_response_schema_openai_and_anthropic() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "pitch"],
        "properties": {
            "title": {"type": "string"},
            "pitch": {"type": "string"},
        },
    }
    openai_payload: dict[str, Any] = {}
    apply_response_schema(openai_payload, schema, style="openai")
    assert openai_payload["response_format"]["type"] == "json_schema"
    assert openai_payload["response_format"]["json_schema"]["schema"] == schema
    deepseek_payload: dict[str, Any] = {}
    apply_response_schema(
        deepseek_payload,
        schema,
        style="openai",
        model_name="deepseek-v4-flash",
    )
    assert "response_format" not in deepseek_payload
    assert deepseek_payload["tools"][0]["function"]["name"] == "book_candidate"
    assert deepseek_payload["tool_choice"]["function"]["name"] == "book_candidate"
    anthropic_payload: dict[str, Any] = {}
    apply_response_schema(anthropic_payload, schema, style="anthropic")
    assert anthropic_payload["tools"][0]["name"] == "book_candidate"
    assert anthropic_payload["tool_choice"] == {"type": "tool", "name": "book_candidate"}


def test_strip_next_openai_compat_field_downgrades_json_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "pitch": {"type": "string"}},
    }
    payload = {
        "stream_options": {"include_usage": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "book_candidate", "schema": schema},
        },
        "reasoning_effort": "high",
    }
    assert strip_next_openai_compat_field(payload) is True
    assert "stream_options" not in payload
    assert "response_format" in payload
    assert strip_next_openai_compat_field(payload) is True
    assert "response_format" not in payload
    assert payload["tools"][0]["function"]["name"] == "book_candidate"
    assert "reasoning_effort" in payload


class _FakeStreamResponse:
    def __init__(
        self,
        lines: list[str],
        status_code: int = 200,
        body: str = "",
    ) -> None:
        self._lines = lines
        self.status_code = status_code
        self._body = body.encode()

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body


class _RecordingAsyncClient:
    def __init__(self, responses: list[_FakeStreamResponse]) -> None:
        self._responses = list(responses)
        self.payloads: list[dict[str, Any]] = []

    @asynccontextmanager
    async def stream(self, *_args: Any, **kwargs: Any) -> AsyncIterator[_FakeStreamResponse]:
        payload = kwargs.get("json") or {}
        self.payloads.append(json.loads(json.dumps(payload)))
        yield self._responses.pop(0)

    async def __aenter__(self) -> "_RecordingAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _ok_lines() -> list[str]:
    return [
        f"data: {json.dumps({'choices': [{'delta': {'content': 'ok'}}]})}",
        "data: [DONE]",
    ]


@pytest.mark.asyncio
async def test_openai_provider_sends_reasoning_effort_for_luna() -> None:
    client = _RecordingAsyncClient([_FakeStreamResponse(_ok_lines())])
    provider = OpenAIProvider(api_key="k", model_name="gpt-5.6-luna")
    with patch("app.model.openai_provider.httpx.AsyncClient", return_value=client):
        chunks = [
            c
            async for c in provider.stream(
                messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                tools=[],
            )
        ]
    assert client.payloads[0]["reasoning_effort"] == "high"
    assert "thinking" not in client.payloads[0]
    assert any(isinstance(c, ModelResponse) for c in chunks)


@pytest.mark.asyncio
async def test_openai_provider_strips_reasoning_on_422() -> None:
    client = _RecordingAsyncClient(
        [
            _FakeStreamResponse([], status_code=400, body="unknown field stream_options"),
            _FakeStreamResponse([], status_code=422, body="unknown field reasoning_effort"),
            _FakeStreamResponse(_ok_lines()),
        ]
    )
    provider = OpenAIProvider(api_key="k", model_name="gpt-5.6-luna")
    with patch("app.model.openai_provider.httpx.AsyncClient", return_value=client):
        chunks = [
            c
            async for c in provider.stream(
                messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                tools=[],
            )
        ]
    assert len(client.payloads) == 3
    assert "stream_options" in client.payloads[0]
    assert "reasoning_effort" in client.payloads[0]
    assert "stream_options" not in client.payloads[1]
    assert client.payloads[1]["reasoning_effort"] == "high"
    assert "reasoning_effort" not in client.payloads[2]
    finals = [c for c in chunks if isinstance(c, ModelResponse)]
    assert finals[-1].text == "ok"
