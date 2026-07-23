from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.model.gateway import (
    ModelFatalError,
    ModelGateway,
    ModelProviderTimeout,
    ModelResponse,
    ModelTransientError,
    classify_http_status,
)
from app.model.generation import GenerationParams


class _ScriptedProvider:
    """Yields scripted outcomes per attempt (exceptions or chunk lists)."""

    def __init__(self, scripts: list[Any]) -> None:
        self.scripts = list(scripts)
        self.calls = 0
        self.abort_seen = False

    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: Any = None,
    ) -> AsyncIterator[str | ModelResponse]:
        self.calls += 1
        if not self.scripts:
            yield ModelResponse(text="empty", output_tokens=1)
            return
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script
        if script == "hang":
            while True:
                if abort and abort.is_set():
                    self.abort_seen = True
                    return
                await asyncio.sleep(0.05)
            return
        for item in script:
            if abort and abort.is_set():
                self.abort_seen = True
                return
            if isinstance(item, (int, float)):
                await asyncio.sleep(float(item))
                continue
            yield item


@pytest.mark.asyncio
async def test_gateway_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 2)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_base_delay_seconds", 0.01)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_max_delay_seconds", 0.05)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)
    monkeypatch.setattr("app.model.gateway.settings.model_timeout_seconds", 30.0)

    provider = _ScriptedProvider(
        [
            ModelTransientError("rate limited", status_code=429, retry_after=0.01),
            [ModelResponse(text="ok-after-retry", output_tokens=3)],
        ]
    )
    gateway = ModelGateway(provider)
    chunks = [c async for c in gateway.stream(messages=[], tools=[])]
    texts = [c.text for c in chunks if isinstance(c, ModelResponse)]
    assert texts == ["ok-after-retry"]
    assert provider.calls == 2
    assert gateway.retry_count == 1


@pytest.mark.asyncio
async def test_gateway_fast_first_byte_timeout_triggers_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 1)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_base_delay_seconds", 0.01)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 0.05)
    monkeypatch.setattr("app.model.gateway.settings.model_timeout_seconds", 30.0)

    provider = _ScriptedProvider(
        [
            "hang",
            [ModelResponse(text="recovered", output_tokens=2)],
        ]
    )
    gateway = ModelGateway(provider)
    chunks = [c async for c in gateway.stream(messages=[], tools=[])]
    texts = [c.text for c in chunks if isinstance(c, ModelResponse)]
    assert texts == ["recovered"]
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_gateway_does_not_retry_after_streaming_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 3)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)

    class FlakyProvider:
        async def stream(self, *, messages, tools, abort=None):
            yield "partial-"
            raise ModelTransientError("boom mid-stream", status_code=503)

    gateway = ModelGateway(FlakyProvider())
    with pytest.raises(ModelFatalError, match="after streaming started"):
        async for _ in gateway.stream(messages=[], tools=[]):
            pass


@pytest.mark.asyncio
async def test_gateway_abort_after_streaming_is_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CancelTurn aclose looks like a transport error; must not become turn.failed."""
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 3)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)

    class AbortAsTransportProvider:
        async def stream(self, *, messages, tools, abort=None):
            yield "partial-"
            if abort is not None:
                # Simulate provider wrapping aclose as transient (openai path).
                raise ModelTransientError("openai transport error: closed")

    gateway = ModelGateway(AbortAsTransportProvider())

    async def cancel_soon() -> None:
        await asyncio.sleep(0.01)
        gateway.abort_stream()

    task = asyncio.create_task(cancel_soon())
    # Race: abort may land before or after the transient raise; either way
    # must not raise ModelFatalError once cancel is set.
    chunks: list[str] = []
    try:
        async for item in gateway.stream(messages=[], tools=[]):
            if isinstance(item, str):
                chunks.append(item)
                gateway.abort_stream()
    except ModelFatalError:
        await task
        raise
    await task
    assert chunks == ["partial-"]


@pytest.mark.asyncio
async def test_gateway_cancel_interrupts_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 5)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_base_delay_seconds", 10.0)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_max_delay_seconds", 10.0)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)
    monkeypatch.setattr("app.model.gateway.settings.model_timeout_seconds", 60.0)

    provider = _ScriptedProvider(
        [ModelTransientError("429", status_code=429, retry_after=10.0)]
    )
    gateway = ModelGateway(provider)

    async def cancel_soon() -> None:
        await asyncio.sleep(0.05)
        gateway.abort_stream()

    task = asyncio.create_task(cancel_soon())
    started = asyncio.get_event_loop().time()
    chunks = [c async for c in gateway.stream(messages=[], tools=[])]
    elapsed = asyncio.get_event_loop().time() - started
    await task
    assert chunks == []
    assert elapsed < 1.0
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_gateway_retries_exhausted_raises_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 1)
    monkeypatch.setattr("app.model.gateway.settings.model_retry_base_delay_seconds", 0.01)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)

    provider = _ScriptedProvider(
        [
            ModelTransientError("503", status_code=503),
            ModelTransientError("503 again", status_code=503),
        ]
    )
    gateway = ModelGateway(provider)
    with pytest.raises(ModelFatalError, match="retries exhausted"):
        async for _ in gateway.stream(messages=[], tools=[]):
            pass
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_gateway_overall_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.model.gateway.settings.model_timeout_seconds", 0.08)
    monkeypatch.setattr("app.model.gateway.settings.model_first_byte_timeout_seconds", 5.0)
    monkeypatch.setattr("app.model.gateway.settings.model_max_retries", 0)

    provider = _ScriptedProvider([[0.2, ModelResponse(text="late", output_tokens=1)]])
    gateway = ModelGateway(provider)
    with pytest.raises(ModelProviderTimeout):
        async for _ in gateway.stream(messages=[], tools=[]):
            pass


def test_classify_http_status_transient_and_fatal() -> None:
    err = classify_http_status(429, body="slow down", headers={"retry-after": "1.5"})
    assert isinstance(err, ModelTransientError)
    assert err.retry_after == 1.5
    err5 = classify_http_status(502, body="bad gateway")
    assert isinstance(err5, ModelTransientError)
    fatal = classify_http_status(400, body="bad request")
    assert isinstance(fatal, ModelFatalError)


def test_generation_params_align_max_tokens_and_writing_temp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.model.generation.settings.context_output_reserve_tokens", 16_384)
    monkeypatch.setattr("app.model.generation.settings.model_max_output_tokens", 0)
    monkeypatch.setattr("app.model.generation.settings.model_temperature_writing", 0.3)
    monkeypatch.setattr("app.model.generation.settings.model_temperature_agent", None)
    monkeypatch.setattr("app.model.generation.settings.model_top_p", None)
    monkeypatch.setattr("app.model.generation.settings.model_tool_choice", "auto")
    monkeypatch.setattr("app.model.generation.settings.model_thinking_enabled", False)

    writing = GenerationParams.from_settings(scenario_id="writing")
    assert writing.max_output_tokens == 16_384
    assert writing.temperature == 0.3
    assert writing.thinking_enabled is False

    agent = GenerationParams.from_settings(scenario_id="agent")
    assert agent.temperature is None
    assert agent.max_output_tokens == 16_384
