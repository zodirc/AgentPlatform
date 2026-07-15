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
