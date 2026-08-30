"""Tests for RemoteModelProvider NDJSON protocol."""

from __future__ import annotations

import json

import httpx
import pytest

from app.model.config import ModelConfig
from app.model.gateway import ModelResponse, StreamActivity
from app.model.remote_provider import RemoteModelProvider


class _StreamTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/complete"
        lines = [
            json.dumps({"t": "delta", "text": "hi "}),
            json.dumps({"t": "activity", "kind": "sse", "text": "…"}),
            json.dumps(
                {
                    "t": "final",
                    "text": "hi there",
                    "tool_calls": None,
                    "input_tokens": 1,
                    "output_tokens": 2,
                }
            ),
        ]
        body = ("\n".join(lines) + "\n").encode()
        return httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"})


@pytest.mark.asyncio
async def test_remote_provider_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.model.remote_provider.settings.internal_service_token",
        "tok",
        raising=False,
    )
    provider = RemoteModelProvider(
        config=ModelConfig(provider="openai", model_name="gpt", api_key="k"),
        base_url="http://gateway.test",
        token="tok",
    )

    chunks: list = []

    async with httpx.AsyncClient(transport=_StreamTransport()) as client:
        # Patch AsyncClient used inside stream by monkeypatching httpx.AsyncClient
        class _Client(httpx.AsyncClient):
            def __init__(self, *a, **k):
                super().__init__(transport=_StreamTransport(), *a, **k)

        monkeypatch.setattr("app.model.remote_provider.httpx.AsyncClient", _Client)
        async for c in provider.stream(messages=[{"role": "user", "content": "x"}], tools=[]):
            chunks.append(c)

    assert chunks[0] == "hi "
    assert isinstance(chunks[1], StreamActivity)
    assert isinstance(chunks[2], ModelResponse)
    assert chunks[2].text == "hi there"
    assert chunks[2].output_tokens == 2
