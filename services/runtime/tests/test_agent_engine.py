from __future__ import annotations

import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.engine.agent_engine import AgentEngine, StepTimeoutError
from app.engine.state import TurnState
from app.model.gateway import ModelProviderTimeout, ModelResponse
from app.tools.core import tools as core
from app.tools.registry import ToolSpec


class FakeGateway:
    def __init__(self, chunks: list[Any], *, one_per_stream: bool = False) -> None:
        self._chunks = chunks
        self._one_per_stream = one_per_stream
        self._cursor = 0

    async def stream(self, *, messages: list[dict], tools: list[dict]) -> AsyncIterator[str | ModelResponse]:
        if self._one_per_stream:
            if self._cursor < len(self._chunks):
                yield self._chunks[self._cursor]
                self._cursor += 1
            return
        for chunk in self._chunks:
            yield chunk


def _state() -> TurnState:
    uid = uuid4()
    return TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=3,
    )


def _stub_tool() -> ToolSpec:
    return ToolSpec(
        name="stub_echo",
        description="echo",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
        handler=core.stub_echo,
    )


def _write_tool() -> ToolSpec:
    return ToolSpec(
        name="write_file",
        description="write",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=core.write_file,
        requires_approval=True,
    )


@pytest.mark.asyncio
async def test_agent_engine_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.engine.agent_engine.settings.turn_token_budget", 10)

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    engine = AgentEngine(
        gateway=FakeGateway([ModelResponse(text="x" * 50, output_tokens=20)]),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    state = _state()
    result = await engine.run(state)
    assert state.budget_exceeded is True
    assert state.termination_reason == "budget_exceeded"
    assert result is not None


@pytest.mark.asyncio
async def test_agent_engine_text_response(workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        events.append(event_type)

    engine = AgentEngine(
        gateway=FakeGateway(["Hello"]),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    result = await engine.run(_state())
    assert result == "Hello"
    assert "step.started" in events
    assert "turn.token" in events


@pytest.mark.asyncio
async def test_agent_engine_stub_echo_terminates(workspace) -> None:
    call = {"id": "tc1", "name": "stub_echo", "input": {"message": "done"}}
    events: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        events.append(event_type)

    engine = AgentEngine(
        gateway=FakeGateway([ModelResponse(tool_calls=[call])]),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    result = await engine.run(_state())
    assert result is not None
    assert "tool.completed" in events


@pytest.mark.asyncio
async def test_agent_engine_waiting_approval(workspace) -> None:
    call = {"id": "tc2", "name": "write_file", "input": {"path": "x.txt", "content": "y"}}
    events: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        events.append(event_type)

    engine = AgentEngine(
        gateway=FakeGateway([ModelResponse(tool_calls=[call])]),
        tools=[_write_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    result = await engine.run(_state())
    assert result == "waiting_approval"
    assert "approval.requested" in events
    assert engine.pending_approval is not None


@pytest.mark.asyncio
async def test_agent_engine_cancel_during_stream() -> None:
    cancel = AsyncMock(side_effect=[(False, False), (True, False)])

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    engine = AgentEngine(
        gateway=FakeGateway(["a", "b", "c"]),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=cancel,
    )
    state = _state()
    result = await engine.run(state)
    assert state.cancelled is True
    assert result is None or isinstance(result, str)


@pytest.mark.asyncio
async def test_agent_engine_model_timeout_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimeoutGateway:
        async def stream(self, *, messages: list[dict], tools: list[dict]) -> AsyncIterator[str]:
            raise ModelProviderTimeout("timeout")
            yield ""  # pragma: no cover

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    engine = AgentEngine(
        gateway=TimeoutGateway(),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    with pytest.raises(ModelProviderTimeout):
        await engine.run(_state())


@pytest.mark.asyncio
async def test_agent_engine_draft_section_streams_deltas(workspace) -> None:
    draft = ToolSpec(
        name="draft_section",
        description="draft",
        parameters={
            "type": "object",
            "properties": {"section_id": {"type": "string"}, "content": {"type": "string"}},
            "required": ["section_id", "content"],
        },
        handler=core.draft_section,
    )
    call = {"id": "tc3", "name": "draft_section", "input": {"section_id": "intro", "content": "abcdefghijklmnop"}}
    deltas: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        if event_type == "section.draft.delta":
            deltas.append(payload["delta"])

    engine = AgentEngine(
        gateway=FakeGateway([ModelResponse(tool_calls=[call])]),
        tools=[draft],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    await engine.run(_state())
    assert deltas
    assert "".join(deltas).startswith("abcdefghijklmnop")


@pytest.mark.asyncio
async def test_agent_engine_records_export_delivery(workspace) -> None:
    sections = workspace / "sections"
    sections.mkdir()
    (sections / "intro.md").write_text("Ready", encoding="utf-8")
    export = ToolSpec(
        name="export_document",
        description="export",
        parameters={
            "type": "object",
            "properties": {
                "section_ids": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["section_ids"],
        },
        handler=core.export_document,
    )
    call = {
        "id": "tc-export",
        "name": "export_document",
        "input": {
            "section_ids": ["intro"],
            "source": "confirmed",
            "output_path": "exports/out.md",
        },
    }
    events: list[tuple[str, dict[str, Any]]] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        events.append((event_type, payload))

    engine = AgentEngine(
        gateway=FakeGateway([ModelResponse(tool_calls=[call])]),
        tools=[export],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    state = _state()
    await engine.run(state)

    assert state.delivery == {
        "delivery_status": "ok",
        "delivery_issues": [],
        "export_path": "exports/out.md",
    }
    completed = [payload for event, payload in events if event == "tool.completed"]
    assert completed[0]["delivery_status"] == "ok"


@pytest.mark.asyncio
async def test_agent_engine_step_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.engine.agent_engine.settings.step_timeout_seconds", 0.001)

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        return None

    class SlowGateway:
        async def stream(self, *, messages: list[dict], tools: list[dict]) -> AsyncIterator[str]:
            import asyncio

            await asyncio.sleep(0.05)
            yield "late"

    engine = AgentEngine(
        gateway=SlowGateway(),
        tools=[_stub_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    with pytest.raises(StepTimeoutError):
        await engine.run(_state())


def _list_dir_tool() -> ToolSpec:
    return ToolSpec(
        name="list_dir",
        description="list",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=core.list_dir,
    )


@pytest.mark.asyncio
async def test_agent_engine_caches_repeat_list_dir(workspace) -> None:
    call1 = {"id": "tc-a", "name": "list_dir", "input": {"path": "."}}
    call2 = {"id": "tc-b", "name": "list_dir", "input": {"path": "."}}
    summaries: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        if event_type == "tool.completed":
            summaries.append(str(payload.get("summary", "")))

    engine = AgentEngine(
        gateway=FakeGateway(
            [
                ModelResponse(tool_calls=[call1]),
                ModelResponse(tool_calls=[call2]),
                ModelResponse(text="done"),
            ]
        ),
        tools=[_list_dir_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    state = _state()
    state.max_steps = 5
    await engine.run(state)
    last_tool_msg = [
        m for m in state.messages if m.get("role") == "tool"
    ][-1]["content"][0]["content"]
    payload = json.loads(last_tool_msg)
    assert payload.get("_cached") is True
    assert payload.get("_repeat_count", 0) >= 2
    assert "_note" in payload


def _search_sources_tool() -> ToolSpec:
    return ToolSpec(
        name="search_sources",
        description="search",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=core.search_sources,
    )


@pytest.mark.asyncio
async def test_agent_engine_search_sources_turn_budget(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.engine.agent_engine.settings.search_sources_max_per_turn", 2)
    monkeypatch.setattr("app.engine.agent_engine.settings.data_dir", str(workspace))
    (workspace / "sources").mkdir()
    (workspace / "sources" / "note.md").write_text("alpha beta", encoding="utf-8")

    calls = [
        {"id": "s1", "name": "search_sources", "input": {"query": "alpha"}},
        {"id": "s2", "name": "search_sources", "input": {"query": "beta"}},
        {"id": "s3", "name": "search_sources", "input": {"query": "gamma"}},
    ]
    statuses: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int) -> None:
        if event_type == "tool.completed" and payload.get("tool_name") == "search_sources":
            statuses.append(str(payload.get("status", "")))

    engine = AgentEngine(
        gateway=FakeGateway(
            [
                ModelResponse(tool_calls=[calls[0]]),
                ModelResponse(tool_calls=[calls[1]]),
                ModelResponse(tool_calls=[calls[2]]),
                ModelResponse(text="done"),
            ],
            one_per_stream=True,
        ),
        tools=[_search_sources_tool()],
        system_prompt="sys",
        write_event=write_event,
        check_cancel=AsyncMock(return_value=(False, False)),
    )
    state = _state()
    state.max_steps = 6
    await engine.run(state)
    assert statuses == ["ok", "ok", "error"]

