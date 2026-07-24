from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState
from app.model.gateway import ModelGateway, ModelResponse, StubModelProvider
from app.scenarios.registry import ScenarioRegistry
from app.tools.bootstrap import build_registry, tool_scope
from app.tools.delegate_context import DelegateRuntime, set_delegate_runtime


@pytest.mark.asyncio
async def test_model_gateway_abort_stops_stub_slow_stream() -> None:
    gateway = ModelGateway(StubModelProvider())
    messages = [{"role": "user", "content": [{"type": "text", "text": "shared.05 slow stream"}]}]
    stream = gateway.stream(messages=messages, tools=[])

    async def collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in stream:
            if isinstance(chunk, str):
                chunks.append(chunk)
            if len(chunks) >= 2:
                gateway.abort_stream()
        return chunks

    chunks = await asyncio.wait_for(collect(), timeout=2.0)
    assert chunks
    assert any(c.startswith("stream-") for c in chunks)


@pytest.mark.asyncio
async def test_delegate_runs_nested_engine() -> None:
    from app.tools import delegate_runner

    profile = ScenarioRegistry.get("writing")
    registry = build_registry()
    tools = tool_scope(profile, registry)
    gateway = ModelGateway(StubModelProvider())
    turn_id = uuid4()
    run_id = uuid4()
    session_id = uuid4()
    trace_id = uuid4()
    events: list[tuple[str, dict]] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int | None = None) -> None:
        events.append((event_type, payload))

    async def check_cancel() -> tuple[bool, bool]:
        return False, False

    set_delegate_runtime(
        DelegateRuntime(
            gateway=gateway,
            parent_profile=profile,
            parent_tools=tools,
            write_event=write_event,
            check_cancel=check_cancel,
            turn_id=turn_id,
            session_id=session_id,
            run_id=run_id,
            trace_id=trace_id,
            scenario_id="writing",
        )
    )
    try:
        result = await delegate_runner.run_delegate(
            task="调研资料 writing.06",
            agent_type="researcher",
            turn_id=turn_id,
            run_id=run_id,
        )
    finally:
        set_delegate_runtime(None)

    assert result["status"] == "completed"
    types = [t for t, _ in events]
    assert "subagent.started" in types
    assert "subagent.completed" in types
    live = [(t, p) for t, p in events if t not in {"subagent.started", "subagent.completed"}]
    assert live, "sub-agent live events should be forwarded"
    assert all(p.get("subagent_id") for _, p in live)
    assert result["subagent_id"]
    assert all(p["subagent_id"] == result["subagent_id"] for _, p in live)


class _SingleTextProvider:
    async def stream(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        abort: asyncio.Event | None = None,
    ):
        for _ in range(10):
            if abort and abort.is_set():
                return
            await asyncio.sleep(0.05)
            yield "tok "


@pytest.mark.asyncio
async def test_agent_engine_abort_stream_on_cancel() -> None:
    gateway = ModelGateway(_SingleTextProvider())
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        max_steps=3,
    )
    calls = 0

    async def write_event(**_) -> None:
        return None

    async def check_cancel() -> tuple[bool, bool]:
        nonlocal calls
        calls += 1
        return calls >= 2, False

    engine = AgentEngine(
        gateway=gateway,
        tools=[],
        system_prompt="test",
        write_event=write_event,
        check_cancel=check_cancel,
    )
    await engine.run(state)
    assert state.cancelled is True
