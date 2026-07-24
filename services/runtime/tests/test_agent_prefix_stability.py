from __future__ import annotations

import hashlib
from pathlib import Path

from app.scenarios.registry import ScenarioRegistry
from app.tools.bootstrap import build_registry, tool_scope


def _agent_system_path() -> Path:
    return Path(__file__).resolve().parents[1] / "app" / "scenarios" / "agent" / "system.md"


def test_agent_system_prompt_contains_cq1_discipline() -> None:
    text = _agent_system_path().read_text(encoding="utf-8")
    assert "## Default loop" in text
    assert "## Ban: anti-patterns" in text
    assert "## Verify" in text
    assert "read_lints" in text
    assert "run_tests" in text
    assert "edit_file" in text
    assert "propose_patch" in text
    assert "minimal" in text.lower()
    assert "head" in text and "tail" in text
    assert "write_file" in text
    assert "user intent this Turn" in text
    assert "## Communicate" in text
    assert "next_offset" in text
    assert "Read-after-complete" in text
    assert "Propose-then-redo" in text
    assert "**`edit_file`**" in text or "Default tool: **`edit_file`**" in text
    assert "按此执行" in text


def test_agent_system_prompt_byte_stable_across_loads() -> None:
    """CQ1 / AQ1: stable prefix requires system.md to be byte-identical across loads."""
    ScenarioRegistry.load()
    a = ScenarioRegistry.get("agent").system_prompt
    ScenarioRegistry.load()
    b = ScenarioRegistry.get("agent").system_prompt
    assert a == b
    assert a == _agent_system_path().read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(a.encode("utf-8")).hexdigest()
    assert digest == hashlib.sha256(b.encode("utf-8")).hexdigest()


def test_agent_tool_descriptions_hygiene() -> None:
    """CQ2: agent-facing tools carry when-to-use guidance; no Phase-1 stubs."""
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    registry = build_registry()
    by_name = {s.name: s for s in tool_scope(profile, registry)}

    write = by_name["write_file"].description
    assert "propose_patch" in write or "edit_file" in write
    assert "Create or overwrite a workspace file" not in write

    tests = by_name["run_tests"].description
    assert "simulated in Phase 1" not in tests.lower()
    assert "pytest" in tests.lower() or "test" in tests.lower()

    lints = by_name["read_lints"].description
    assert "write_file" in lints or "edit_file" in lints or "propose_patch" in lints

    search = by_name["search_codebase"].description
    assert "grep" in search
    assert len(search) > 40

    cmd = by_name["run_command"].description
    assert "read_file" in cmd or "run_tests" in cmd
    assert "approval" in cmd.lower()
    assert "head" in cmd.lower() or "FORBIDDEN" in cmd

    read = by_name["read_file"].description
    assert "complete" in read.lower() or "truncated=false" in read.lower()
    params = by_name["read_file"].parameters.get("properties") or {}
    assert "offset" in params and "limit" in params

    edit = by_name["edit_file"].description
    assert "default" in edit.lower() or "prefer this over propose_patch" in edit.lower()

    propose = by_name["propose_patch"].description
    assert "pending" in propose.lower() or "does not modify" in propose.lower()
    assert "edit_file" in propose

    # Tool schemas (names + descriptions) must be deterministic for cache prefix.
    tools = registry.to_openai_tools(list(by_name))
    again = registry.to_openai_tools(list(by_name))
    assert tools == again
