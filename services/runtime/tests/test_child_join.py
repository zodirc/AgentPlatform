from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.controller.child_join import join_children


@pytest.mark.asyncio
async def test_join_children_gathers_readonly() -> None:
    started: list[float] = []

    async def fake_execute(**kwargs):
        started.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.05)
        return {"status": "completed", "summary": kwargs["agent_type"]}

    children = [
        {"tool_call_id": "a", "agent_type": "explore", "task": "one"},
        {"tool_call_id": "b", "agent_type": "retrieve", "task": "two"},
    ]
    with patch("app.tools.delegate_runner.execute_delegate", new=fake_execute):
        out = await join_children(children)
    assert set(out) == {"a", "b"}
    assert abs(started[0] - started[1]) < 0.04
