from __future__ import annotations

from dataclasses import replace

import pytest

from app.scenarios.registry import ScenarioProfile, ScenarioRegistry
from app.tools.bootstrap import build_registry, tool_scope
from app.tools.registry import ON_WRITE_TOOLS, ToolRegistry, ToolSpec


@pytest.mark.asyncio
async def test_registry_list_and_openai_tools() -> None:
    async def handler(**_kwargs):
        return {"ok": True}

    registry = ToolRegistry()
    spec = ToolSpec(
        name="demo",
        description="demo tool",
        parameters={"type": "object"},
        handler=handler,
    )
    registry.register(spec)
    assert registry.get("demo") is spec
    assert registry.list_for_names(["demo", "missing"]) == [spec]
    tools = registry.to_openai_tools(["demo"])
    assert tools[0]["name"] == "demo"
    assert ON_WRITE_TOOLS  # referenced for coverage


def test_build_registry_has_core_tools() -> None:
    registry = build_registry()
    assert registry.get("read_file") is not None
    assert registry.get("run_command") is not None
    assert registry.get("delegate") is not None


def test_tool_scope_on_write_override() -> None:
    ScenarioRegistry.load()
    profile = replace(
        ScenarioRegistry.get("agent"),
        approval_overrides={"run_command": "on_write", "write_file": "on_write"},
    )
    registry = build_registry()
    specs = {s.name: s for s in tool_scope(profile, registry)}
    assert specs["run_command"].requires_approval is False
    assert specs["write_file"].requires_approval is True


def test_tool_scope_never_override() -> None:
    ScenarioRegistry.load()
    profile = replace(
        ScenarioRegistry.get("agent"),
        approval_overrides={"run_command": "never"},
    )
    registry = build_registry()
    specs = {s.name: s for s in tool_scope(profile, registry)}
    assert specs["run_command"].requires_approval is False


def test_writing_profile_lists_writing_subagents() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    assert set(profile.subagent_types) == {
        "researcher",
        "drafter",
        "editor",
        "fact_checker",
        "stylist",
        "explore",
        "retrieve",
        "planner",
    }
    assert "grep" in profile.tool_names
    assert "glob" in profile.tool_names


def test_agent_profile_lists_six_subagents() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    assert set(profile.subagent_types) >= {
        "explore",
        "retrieve",
        "verify",
        "edit",
        "planner",
        "shell",
    }


def test_tool_scope_skips_unknown_tools() -> None:
    profile = ScenarioProfile(
        scenario_id="custom",
        display_name="custom",
        tool_names=["missing_tool"],
        system_prompt="x",
        approval_overrides={},
    )
    registry = build_registry()
    specs = tool_scope(profile, registry)
    assert len(specs) == 1
    assert specs[0].name == "stub_echo"
