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
async def test_tool_executor_unknown_tool() -> None:
    executor = ToolExecutor([])
    result = await executor.run(
        tool_name="missing",
        tool_call_id="c1",
        arguments={},
        state=type("S", (), {"turn_id": None, "run_id": None})(),
    )
    assert "error" in result
