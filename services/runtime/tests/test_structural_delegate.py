from __future__ import annotations

from app.tools.bootstrap import build_registry, tool_scope
from app.tools.delegate_runner import _resolve_sub_tools
from app.scenarios.registry import ScenarioRegistry


def test_writing_explore_never_gets_nav() -> None:
    ScenarioRegistry.load()
    writing = ScenarioRegistry.get("writing")
    parent = tool_scope(writing, build_registry())
    names = {s.name for s in _resolve_sub_tools(parent, "explore")}
    assert "goto_definition" not in names
    assert "find_references" not in names
    assert "grep" in names


def test_agent_explore_gets_nav() -> None:
    ScenarioRegistry.load()
    agent = ScenarioRegistry.get("agent")
    parent = tool_scope(agent, build_registry())
    names = {s.name for s in _resolve_sub_tools(parent, "explore")}
    assert "goto_definition" in names
    assert "find_references" in names
