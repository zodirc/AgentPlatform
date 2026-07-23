from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.controller import turn_controller as tc
from app.controller.pending_store import PendingTurn, save
from app.engine.state import TurnState
from app.scenarios.registry import ScenarioRegistry
from app.tools.bootstrap import build_registry, tool_scope


@pytest.fixture(autouse=True)
def _clean_registry():
    tc._active_turns.clear()
    yield
    tc._active_turns.clear()


def _pool_conn() -> tuple[object, list[tuple[str, tuple]]]:
    executed: list[tuple[str, tuple]] = []

    class _Conn:
        async def execute(self, query: str, *args) -> None:
            executed.append((query, args))

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_args) -> None:
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

        async def fetchval(self, query: str, *args) -> str | None:
            return "completed"

    return _Pool(), executed


def _pending_turn(*, turn_id, run_id, trace_id, tool_call_id: str) -> PendingTurn:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    registry = build_registry()
    tools = tool_scope(profile, registry)
    state = TurnState(
        turn_id=turn_id,
        session_id=uuid4(),
        run_id=run_id,
        trace_id=trace_id,
        scenario_id="writing",
        messages=[],
        step_count=1,
    )
    return PendingTurn(
        state=state,
        profile=profile,
        tools=tools,
        gateway=AsyncMock(),
        trace_id=trace_id,
        pending_tool_call={
            "tool_call_id": tool_call_id,
            "tool_name": "write_file",
            "arguments": {"path": "draft.md", "content": "hello"},
            "step_index": 1,
        },
        system_prompt=profile.system_prompt,
    )


@pytest.mark.asyncio
async def test_run_turn_help_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    session_id = uuid4()
    trace_id = uuid4()
    appended: list[str] = []

    class _Conn:
        async def execute(self, *_args, **_kwargs) -> None:
            return None

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_args) -> None:
            return None

    class _Pool:
        def acquire(self):
            return _Acquire()

    async def fake_append_event(_conn, *, event_type: str, **_kwargs) -> int:
        appended.append(event_type)
        return len(appended)

    monkeypatch.setattr(tc, "get_pool", AsyncMock(return_value=_Pool()))
    monkeypatch.setattr(tc, "append_event", fake_append_event)
    monkeypatch.setattr(tc, "load_session_context", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "load_session_transcript", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "load_session_owner_user_id", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "resolve_model_config", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "resolve_active_profile_metadata", AsyncMock(return_value=None))
    monkeypatch.setattr(tc.settings, "runtime_runner_id", "runtime-test")
    monkeypatch.setattr(tc, "run_via_langgraph", AsyncMock())

    await tc._run_turn(
        turn_id=turn_id,
        run_id=run_id,
        session_id=session_id,
        scenario_id="writing",
        message="/help",
        trace_id=trace_id,
    )

    assert "turn.accepted" in appended
    assert "turn.completed" in appended
    tc.run_via_langgraph.assert_not_called()


@pytest.mark.asyncio
async def test_start_turn_claims_run_before_run_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    claim = AsyncMock(return_value=True)
    run_turn = AsyncMock()
    monkeypatch.setattr(tc, "run_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(tc, "ensure_run_owned_by_runner", claim)
    monkeypatch.setattr(tc, "_run_turn", run_turn)
    # start_turn imports ensure_work_root_exists lazily; on GHA the default
    # WORKSPACE_ROOT=/workspace is not writable for the runner user, which
    # would swallow the failure in start_turn's except and skip _run_turn.
    import app.tenant_context as tenant_context

    monkeypatch.setattr(tenant_context, "ensure_work_root_exists", lambda: None)
    monkeypatch.setattr(tc, "_fail_turn", AsyncMock())

    await tc.start_turn(
        turn_id=turn_id,
        run_id=run_id,
        session_id=uuid4(),
        scenario_id="writing",
        message="hello",
        trace_id=uuid4(),
    )
    claim.assert_awaited_once_with(run_id=run_id)
    run_turn.assert_awaited_once()


@pytest.mark.asyncio
async def test_deny_tool_call_resumes_via_langgraph(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()
    tool_call_id = "call-deny-1"
    pending = _pending_turn(
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
    )
    save(turn_id, pending)

    pool, _ = _pool_conn()
    events: list[dict] = []
    appended: list[str] = []

    async def fake_write_event(**kwargs) -> None:
        events.append(kwargs)

    async def fake_make_write_event(**_kwargs):
        return fake_write_event

    async def fake_append_event(_conn, *, event_type: str, **_kwargs) -> int:
        appended.append(event_type)
        return len(appended)

    finalize = AsyncMock()
    run_lg = AsyncMock(return_value="completed")

    monkeypatch.setattr(tc, "_wait_turn_inactive", AsyncMock(return_value=True))
    monkeypatch.setattr(tc, "load_checkpoint", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "delete_checkpoint", AsyncMock())
    monkeypatch.setattr(tc, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(tc, "append_event", fake_append_event)
    monkeypatch.setattr(tc, "_make_write_event", fake_make_write_event)
    monkeypatch.setattr(tc, "_check_cancel_flag", AsyncMock(return_value=(False, False)))
    monkeypatch.setattr(tc, "run_via_langgraph", run_lg)
    monkeypatch.setattr(tc, "_finalize_turn", finalize)
    monkeypatch.setattr(tc, "_cleanup_pending_after_command", AsyncMock())
    monkeypatch.setattr(tc, "resolve_model_config", AsyncMock(return_value=None))
    monkeypatch.setattr(tc, "resolve_context_window_tokens", AsyncMock(return_value=128000))
    monkeypatch.setattr(tc, "load_session_owner_user_id", AsyncMock(return_value=None))

    async def _passthrough_tenant(_session_id, coro):
        return await coro

    monkeypatch.setattr(tc, "_with_session_tenant", _passthrough_tenant)
    monkeypatch.setattr(tc.settings, "runtime_runner_id", "runtime-test")

    await tc.deny_tool_call(
        turn_id=turn_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        trace_id=trace_id,
        reason="user_denied",
    )

    assert "approval.resolved" in appended
    denied = next(e for e in events if e["event_type"] == "tool.completed")
    assert denied["payload"]["status"] == "denied"
    run_lg.assert_awaited_once()
    finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_tool_call_mismatch_skips_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    turn_id = uuid4()
    run_id = uuid4()
    trace_id = uuid4()
    pending = _pending_turn(
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        tool_call_id="expected-id",
    )
    save(turn_id, pending)
    run_lg = AsyncMock()

    monkeypatch.setattr(tc, "_wait_turn_inactive", AsyncMock(return_value=True))
    monkeypatch.setattr(tc, "_resolve_pending", AsyncMock(return_value=pending))
    monkeypatch.setattr(tc, "run_via_langgraph", run_lg)
    monkeypatch.setattr(tc, "_cleanup_pending_after_command", AsyncMock())

    async def _passthrough_tenant(_session_id, coro):
        return await coro

    monkeypatch.setattr(tc, "_with_session_tenant", _passthrough_tenant)

    await tc.approve_tool_call(
        turn_id=turn_id,
        run_id=run_id,
        tool_call_id="wrong-id",
        trace_id=trace_id,
    )

    run_lg.assert_not_called()
