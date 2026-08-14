from __future__ import annotations

import pytest

from app.tools import delegate_runner


@pytest.mark.parametrize(
    "agent_type",
    [
        "researcher",
        "drafter",
        "editor",
        "fact_checker",
        "stylist",
        "explore",
        "retrieve",
        "planner",
    ],
)
def test_writing_subagent_types_have_tool_mappings(agent_type: str) -> None:
    assert agent_type in delegate_runner.SUBAGENT_TOOL_NAMES
    assert delegate_runner.SUBAGENT_TOOL_NAMES[agent_type]


def test_writing_allows_explore_by_default() -> None:
    from app.scenarios.registry import ScenarioRegistry

    profile = ScenarioRegistry.get("writing")
    allowed = delegate_runner._allowed_subagent_types(
        "writing", list(profile.subagent_types)
    )
    assert "explore" in allowed
    assert "retrieve" in allowed
    assert "planner" in allowed


def test_empty_subagent_types_raises() -> None:
    with pytest.raises(ValueError, match="empty subagent_types"):
        delegate_runner._allowed_subagent_types("writing", [])


@pytest.mark.parametrize(
    "agent_type",
    ["explore", "retrieve", "verify", "edit", "planner", "shell"],
)
def test_agent_subagent_types_have_tool_mappings(agent_type: str) -> None:
    assert agent_type in delegate_runner.SUBAGENT_TOOL_NAMES
    assert delegate_runner.SUBAGENT_TOOL_NAMES[agent_type]


def test_build_delegate_prompt_prefers_path_pointers() -> None:
    prompt = delegate_runner._build_delegate_prompt(
        task="Summarize chapter",
        context="x" * 5_000,
        context_refs=["sources/a.md", "outline.md"],
        paths=["sections/01.md"],
        hot_files=["notes.md", "sources/a.md"],
    )
    assert "Summarize chapter" in prompt
    assert "[context_refs]" in prompt
    assert "sources/a.md" in prompt
    assert "outline.md" in prompt
    assert "sections/01.md" in prompt
    assert "[hot_files]" in prompt
    assert "notes.md" in prompt
    # pasted context is truncated rather than dumping 5k fully as the only signal
    assert len(prompt) < 5_000 + 500


def test_extract_artifact_refs_from_summary() -> None:
    refs = delegate_runner._extract_artifact_refs(
        "Notes done.\nARTIFACT_REFS: artifacts/collab/findings.md, `src/a.py`\nMore text."
    )
    assert refs == ["artifacts/collab/findings.md", "src/a.py"]
    assert delegate_runner._extract_artifact_refs("no refs here") == []


def test_verify_subagent_includes_run_command() -> None:
    names = delegate_runner.SUBAGENT_TOOL_NAMES["verify"]
    assert "run_command" in names
    assert "run_tests" in names
    from app.tools.bootstrap import build_registry

    # Even if parent profile omits run_command, verify still gets it from registry.
    parent = [s for s in [build_registry().get("read_file"), build_registry().get("run_tests")] if s]
    sub = delegate_runner._resolve_sub_tools(parent, "verify")
    assert {s.name for s in sub} >= {"read_file", "run_tests", "run_command"}
    assert all(not s.requires_approval for s in sub)


def test_subagent_tools_waive_approval() -> None:
    from app.tools.bootstrap import build_registry

    registry = build_registry()
    parent = [s for s in [registry.get("write_file"), registry.get("edit_file")] if s]
    assert any(s.requires_approval for s in parent)
    sub = delegate_runner._resolve_sub_tools(parent, "edit")
    assert sub
    assert all(not s.requires_approval for s in sub)


def test_delegate_tool_timeout_covers_nested_engine() -> None:
    from app.tools.bootstrap import build_registry

    spec = build_registry().get("delegate")
    assert spec is not None
    assert spec.timeout_s >= 300.0


def test_tool_batch_outcome_avoids_control_collision() -> None:
    from app.engine.agent_engine import _tool_batch_outcome

    assert _tool_batch_outcome("waiting_approval") == "tool_summary:waiting_approval"
    assert _tool_batch_outcome("ok done") == "ok done"


def test_artifact_refs_from_last_delegate_tool_result() -> None:
    import json

    from app.model.gateway import _artifact_refs_from_last_delegate_result

    messages = [
        {
            "role": "tool",
            "content": [
                {
                    "type": "tool_result",
                    "content": json.dumps(
                        {
                            "subagent_id": "sub-abc",
                            "summary": "ok",
                            "artifact_refs": ["artifacts/collab/findings.md"],
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        }
    ]
    assert _artifact_refs_from_last_delegate_result(messages) == [
        "artifacts/collab/findings.md"
    ]
