from __future__ import annotations

from pathlib import Path

from app.controller.input_compiler import (
    InputCompiler,
    LINT_EXPAND,
    OUTLINE_EXPAND,
    POLISH_EXPAND,
    TEST_EXPAND,
    detect_plan_hint,
    expand_agent_slash,
    expand_writing_slash,
    should_query,
)
from app.context.project import build_runtime_context
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


def test_detect_plan_hint_numbered_goals() -> None:
    msg = "Please do these:\n1. fix lint\n2. add tests\n3. update docs\nThanks"
    assert detect_plan_hint(msg) is not None
    assert "plan_hint" in InputCompiler().compile(msg).metadata


def test_detect_plan_hint_skips_short_single_goal() -> None:
    assert detect_plan_hint("fix the typo in README") is None
    assert "plan_hint" not in InputCompiler().compile("fix the typo in README").metadata


def test_runtime_context_includes_plan_hint() -> None:
    text = build_runtime_context(
        scenario_id="agent",
        step_count=1,
        max_steps=40,
        plan_hint="consider update_plan",
    )
    assert "[plan_hint]" in text
    assert "update_plan" in text


def test_should_query_compact_requests_session_compact() -> None:
    result = should_query("/compact", has_model_key=True)
    assert result.should_query is False
    assert result.slash_command == "compact"


def test_expand_polish_and_outline_deterministic() -> None:
    a, name_a = expand_writing_slash("/polish 去套话")
    b, name_b = expand_writing_slash("/polish 去套话")
    assert name_a == name_b == "polish"
    assert a == b
    assert a.startswith(POLISH_EXPAND)
    assert "去套话" in a
    assert "search_sources" in a

    o, name_o = expand_writing_slash("/outline")
    assert name_o == "outline"
    assert o == OUTLINE_EXPAND
    assert should_query("/polish", has_model_key=True).should_query is True
    assert should_query("/outline", has_model_key=True).should_query is True


def test_expand_agent_test_and_lint_deterministic() -> None:
    a, name_a = expand_agent_slash("/test agent.11")
    b, name_b = expand_agent_slash("/test agent.11")
    assert name_a == name_b == "test"
    assert a == b
    assert a.startswith(TEST_EXPAND)
    assert "run_tests" in a
    assert "agent.11" in a

    l, name_l = expand_agent_slash("/lint app.py")
    assert name_l == "lint"
    assert l.startswith(LINT_EXPAND)
    assert "read_lints" in l
    assert "app.py" in l
    assert should_query("/test", has_model_key=True).should_query is True
    assert should_query("/lint", has_model_key=True).should_query is True


def test_input_compiler_expands_test_into_user_message() -> None:
    compiled = InputCompiler().compile("/test agent.11")
    text = compiled.messages[0]["content"][0]["text"]
    assert compiled.metadata.get("slash_expand") == "test"
    assert text.startswith("[test]")
    assert "run_tests" in text


def test_help_lists_test_and_lint() -> None:
    help_text = should_query("/help", has_model_key=True).local_response or ""
    assert "/test" in help_text
    assert "/lint" in help_text


def test_input_compiler_expands_polish_into_user_message() -> None:
    compiled = InputCompiler().compile("/polish writing.12")
    text = compiled.messages[0]["content"][0]["text"]
    assert compiled.metadata.get("slash_expand") == "polish"
    assert text.startswith("[polish]")
    assert "/polish" not in text.split("\n")[0] or "[polish]" in text


def test_polish_expand_does_not_change_system_prefix_hash(tmp_path: Path) -> None:
    from app.writing.cards import prepare_writing_system_prompt

    root = tmp_path / "sources" / "cards" / "style"
    root.mkdir(parents=True)
    (root / "v.md").write_text("---\nkind: style\n---\n## Voice\ncold\n", encoding="utf-8")
    base = "You are a writing assistant."
    pin_a = prepare_writing_system_prompt(base, "普通改稿", workspace_root=tmp_path)
    pin_b = prepare_writing_system_prompt(
        base,
        expand_writing_slash("/polish")[0],
        workspace_root=tmp_path,
    )
    assert pin_a.event_payload()["prefix_hash"] == pin_b.event_payload()["prefix_hash"]


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
