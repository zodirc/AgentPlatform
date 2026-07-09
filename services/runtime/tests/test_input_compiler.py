from __future__ import annotations

from app.controller.input_compiler import InputCompiler, should_query
from app.tools.bootstrap import build_registry, tool_scope
from app.scenarios.registry import ScenarioRegistry


def test_should_query_help_short_circuits() -> None:
    result = should_query("/help", has_model_key=True)
    assert result.should_query is False
    assert result.local_response
    assert "/help" in result.local_response


def test_should_query_version_short_circuits() -> None:
    result = should_query("/version", has_model_key=True)
    assert result.should_query is False
    assert "v0.1.0" in (result.local_response or "")


def test_should_query_empty_fails() -> None:
    result = should_query("   ", has_model_key=True)
    assert result.should_query is False
    assert result.failure_reason == "empty_message"


def test_should_query_normal_message() -> None:
    assert should_query("hello", has_model_key=False).should_query is True


def test_input_compiler_adds_selection() -> None:
    compiled = InputCompiler().compile("hello", selection="snippet")
    assert compiled.metadata.get("has_selection") is True
    assert "snippet" in compiled.messages[0]["content"][0]["text"]


def test_input_compiler_expands_path_refs() -> None:
    compiled = InputCompiler().compile("please update @sections/01.md")
    assert compiled.metadata.get("path_refs") == ["sections/01.md"]
    assert "sections/01.md" in compiled.messages[0]["content"][0]["text"]


def test_should_query_compact_short_circuits() -> None:
    result = should_query("/compact", has_model_key=True)
    assert result.should_query is False
    assert result.local_response


def test_tool_scope_applies_agent_approval_overrides() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    registry = build_registry()
    specs = {s.name: s for s in tool_scope(profile, registry)}
    assert specs["run_command"].requires_approval is True
    assert specs["read_file"].requires_approval is False
    assert specs["delegate"].requires_approval is True


def test_writing_profile_includes_update_plan() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    assert "update_plan" in profile.tool_names
