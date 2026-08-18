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
async def test_tool_executor_ops_eval_auto_approves() -> None:
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
    assert result.get("ok") is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_tool_executor_sticky_write_approval_skips_gate() -> None:
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

    allowed = await executor.run(
        tool_name="edit_file",
        tool_call_id="c2",
        arguments={},
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
    assert allowed.get("ok") is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_run_command_sticky_skips_approval_after_preapprove() -> None:
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
    assert allowed.get("ok") is True
    assert called["n"] == 1


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
