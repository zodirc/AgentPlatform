from __future__ import annotations

import pytest

from app.tools import delegate_runner


@pytest.mark.parametrize(
    "agent_type",
    ["researcher", "drafter", "editor", "fact_checker", "stylist"],
)
def test_writing_subagent_types_have_tool_mappings(agent_type: str) -> None:
    assert agent_type in delegate_runner.SUBAGENT_TOOL_NAMES
    assert delegate_runner.SUBAGENT_TOOL_NAMES[agent_type]


@pytest.mark.parametrize(
    "agent_type",
    ["explore", "retrieve", "verify", "edit", "planner", "shell"],
)
def test_agent_subagent_types_have_tool_mappings(agent_type: str) -> None:
    assert agent_type in delegate_runner.SUBAGENT_TOOL_NAMES
    assert delegate_runner.SUBAGENT_TOOL_NAMES[agent_type]
