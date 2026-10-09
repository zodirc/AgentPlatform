from __future__ import annotations

import pytest

from app.context.engine import ToolExecutor
from app.tools.registry import ToolSpec
from app.tools.validate import extract_citation_ids, validate_tool_arguments


def test_validate_tool_arguments_missing_required() -> None:
    invalid = validate_tool_arguments(
        tool_name="read_file",
        arguments={},
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    assert invalid is not None
    assert invalid["error"] == "invalid_arguments"
    assert "path" in invalid["missing"]


def test_validate_tool_arguments_ok() -> None:
    assert (
        validate_tool_arguments(
            tool_name="read_file",
            arguments={"path": "notes.md"},
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        is None
    )


def test_validate_tool_arguments_rejects_non_object() -> None:
    invalid = validate_tool_arguments(
        tool_name="read_file",
        arguments="notes.md",  # type: ignore[arg-type]
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )
    assert invalid is not None
    assert "JSON object" in invalid["summary"]


def test_extract_citation_ids() -> None:
    text = "Foo [cite:ref-a] and cite:Book.X then [cite:ref-a] again."
    assert extract_citation_ids(text) == ["cite:ref-a", "cite:Book.X"]


def test_extract_citation_ids_cjk() -> None:
    assert extract_citation_ids("——她有自己的路。[cite:亮剑]") == ["cite:亮剑"]


@pytest.mark.asyncio
async def test_tool_executor_schema_gate_blocks_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True}

    monkeypatch.setattr("app.settings.settings.tool_schema_validate", True)
    executor = ToolExecutor(
        [
            ToolSpec(
                name="read_file",
                description="x",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=handler,
            )
        ]
    )
    result = await executor.run(
        tool_name="read_file",
        tool_call_id="c1",
        arguments={},
        state=type("S", (), {"turn_id": None, "run_id": None})(),
    )
    assert called["n"] == 0
    assert result["error"] == "invalid_arguments"
    assert "path" in result["missing"]


@pytest.mark.asyncio
async def test_tool_executor_requires_approval() -> None:
    async def handler(**_kwargs):
        return {"ok": True}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="danger",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    result = await executor.run(
        tool_name="danger",
        tool_call_id="c1",
        arguments={},
        state=type("S", (), {"turn_id": None, "run_id": None})(),
    )
    assert result["status"] == "approval_required"


@pytest.mark.asyncio
async def test_tool_executor_ops_eval_does_not_skip_approval() -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "wrote"}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="write_file",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    result = await executor.run(
        tool_name="write_file",
        tool_call_id="c1",
        arguments={},
        state=type(
            "S",
            (),
            {
                "ops_eval": True,
                "writes_preapproved": False,
                "exec_preapproved": False,
                "turn_id": None,
                "run_id": None,
                "session_id": None,
                "plan_phase": None,
                "scenario_id": "agent",
            },
        )(),
    )
    assert result["status"] == "approval_required"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_tool_executor_write_approval_is_not_sticky() -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "edited"}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="edit_file",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    blocked = await executor.run(
        tool_name="edit_file",
        tool_call_id="c1",
        arguments={},
        state=type(
            "S",
            (),
            {
                "writes_preapproved": False,
                "turn_id": None,
                "run_id": None,
                "session_id": None,
                "plan_phase": None,
                "scenario_id": "writing",
            },
        )(),
    )
    assert blocked["status"] == "approval_required"
    assert called["n"] == 0

    still_blocked = await executor.run(
        tool_name="edit_file",
        tool_call_id="c2",
        arguments={"path": "a.txt"},
        state=type(
            "S",
            (),
            {
                "writes_preapproved": True,
                "turn_id": None,
                "run_id": None,
                "session_id": None,
                "plan_phase": None,
                "scenario_id": "writing",
            },
        )(),
    )
    assert still_blocked["status"] == "approval_required"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_exec_preapproved_does_not_skip_approval() -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "ran"}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="run_command",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    blocked = await executor.run(
        tool_name="run_command",
        tool_call_id="c1",
        arguments={},
        state=_minimal_state(exec_preapproved=False),
    )
    assert blocked["status"] == "approval_required"
    assert called["n"] == 0

    allowed = await executor.run(
        tool_name="run_command",
        tool_call_id="c2",
        arguments={},
        state=_minimal_state(exec_preapproved=True),
    )
    assert allowed["status"] == "approval_required"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_run_command_allowlist_skips_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True, "summary": "ran"}

    async def allowed(_state, _arguments):
        return True

    monkeypatch.setattr(
        "app.tools.command_allowlist.command_is_allowlisted",
        allowed,
    )
    executor = ToolExecutor(
        [
            ToolSpec(
                name="run_command",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    result = await executor.run(
        tool_name="run_command",
        tool_call_id="c1",
        arguments={"command": "pytest -q"},
        state=_minimal_state(exec_preapproved=False),
    )
    assert result.get("ok") is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_approval_grant_must_match_this_call() -> None:
    from app.policy.approval import POLICY_VERSION, ApprovalGrant, canonical_args_hash

    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="edit_file",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    arguments = {"path": "a.txt", "old_text": "a", "new_text": "b"}
    grant = ApprovalGrant(
        tool_name="edit_file",
        tool_call_id="c1",
        args_hash=canonical_args_hash(arguments),
        policy_version=POLICY_VERSION,
    )
    allowed = await executor.run(
        tool_name="edit_file",
        tool_call_id="c1",
        arguments=arguments,
        state=_minimal_state(),
        approval=grant,
    )
    assert allowed.get("ok") is True
    swapped = await executor.run(
        tool_name="edit_file",
        tool_call_id="c1",
        arguments={"path": "other.txt"},
        state=_minimal_state(),
        approval=grant,
    )
    assert swapped["status"] == "approval_required"
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_remember_after_external_tool_requires_approval() -> None:
    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"status": "remembered"}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="search_sources",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=False,
            ),
            ToolSpec(
                name="remember",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=False,
            ),
        ]
    )
    state = _minimal_state(saw_external=False)
    await executor.run(
        tool_name="search_sources",
        tool_call_id="s1",
        arguments={"query": "x"},
        state=state,
    )
    assert state.saw_external is True
    blocked = await executor.run(
        tool_name="remember",
        tool_call_id="m1",
        arguments={"text": "poison"},
        state=state,
    )
    assert blocked["status"] == "approval_required"
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_subagent_write_is_rejected_instead_of_approval() -> None:
    from app.tools.delegate_context import bump_delegate_depth, reset_delegate_depth

    called = {"n": 0}

    async def handler(**_kwargs):
        called["n"] += 1
        return {"ok": True}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="write_file",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                requires_approval=True,
            )
        ]
    )
    token = bump_delegate_depth()
    try:
        result = await executor.run(
            tool_name="write_file",
            tool_call_id="c1",
            arguments={"path": "a.txt", "content": "x"},
            state=_minimal_state(),
        )
    finally:
        reset_delegate_depth(token)
    assert result["error"] == "需要父代理执行"
    assert called["n"] == 0


def _minimal_state(**extra: object) -> object:
    base = {
        "turn_id": None,
        "run_id": None,
        "session_id": None,
        "plan_phase": None,
        "scenario_id": "writing",
        "turn_user_text": "",
    }
    base.update(extra)
    return type("S", (), base)()


@pytest.mark.asyncio
async def test_tool_executor_timeout() -> None:
    async def handler(**_kwargs):
        import asyncio

        await asyncio.sleep(60)
        return {"ok": True}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="slow",
                description="x",
                parameters={"type": "object"},
                handler=handler,
                timeout_s=0.01,
            )
        ]
    )
    result = await executor.run(
        tool_name="slow",
        tool_call_id="c1",
        arguments={},
        state=_minimal_state(),
    )
    assert result["status"] == "timeout"
    assert "timed out" in result["summary"]


@pytest.mark.asyncio
async def test_tool_executor_type_error_maps_to_invalid_arguments() -> None:
    async def handler(*, path: str, **_kwargs):
        return {"ok": True, "path": path}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="needs_path",
                description="x",
                parameters={"type": "object"},
                handler=handler,
            )
        ]
    )
    result = await executor.run(
        tool_name="needs_path",
        tool_call_id="c1",
        arguments={},
        state=_minimal_state(),
    )
    assert result["error"] == "invalid_arguments"
    assert result["tool_name"] == "needs_path"


@pytest.mark.asyncio
async def test_tool_executor_handler_exception() -> None:
    async def handler(**_kwargs):
        raise RuntimeError("boom")

    executor = ToolExecutor(
        [
            ToolSpec(
                name="boom",
                description="x",
                parameters={"type": "object"},
                handler=handler,
            )
        ]
    )
    result = await executor.run(
        tool_name="boom",
        tool_call_id="c1",
        arguments={},
        state=_minimal_state(),
    )
    assert result == {"error": "boom"}


@pytest.mark.asyncio
async def test_tool_executor_passes_turn_user_text() -> None:
    seen: dict[str, object] = {}

    async def handler(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    executor = ToolExecutor(
        [
            ToolSpec(
                name="draft_section",
                description="x",
                parameters={"type": "object"},
                handler=handler,
            )
        ]
    )
    result = await executor.run(
        tool_name="draft_section",
        tool_call_id="c1",
        arguments={"section_id": "ch1", "content": "x"},
        state=_minimal_state(turn_user_text="写 300 字"),
    )
    assert result.get("ok") is True
    assert seen["turn_user_text"] == "写 300 字"


@pytest.mark.asyncio
async def test_tool_executor_unknown_tool() -> None:
    executor = ToolExecutor([])
    result = await executor.run(
        tool_name="missing",
        tool_call_id="c1",
        arguments={},
        state=type("S", (), {"turn_id": None, "run_id": None})(),
    )
    assert "error" in result
