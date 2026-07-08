from __future__ import annotations

import pytest

from app.context.engine import ToolExecutor
from app.tools.registry import ToolSpec


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
