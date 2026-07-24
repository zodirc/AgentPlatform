from __future__ import annotations

import pytest

from app.controller.plan_phase import normalize_plan_phase, plan_phase_block, system_prompt_for_phase
from app.tools.bootstrap import PLANNING_TOOL_ALLOWLIST, build_registry, tool_scope
from app.scenarios.registry import ScenarioRegistry


def test_normalize_plan_phase() -> None:
    assert normalize_plan_phase(None) is None
    assert normalize_plan_phase("planning") == "planning"
    assert normalize_plan_phase("EXECUTING") == "executing"
    assert normalize_plan_phase("ready") is None


def test_system_prompt_for_phase_appends() -> None:
    base = "You are an agent."
    planning = system_prompt_for_phase(base, "planning")
    executing = system_prompt_for_phase(base, "executing")
    assert "planning" in planning.lower()
    assert "unavailable" in planning.lower()
    assert "executing" in executing.lower()
    assert "in_progress" in executing
    assert system_prompt_for_phase(base, None) == base


def test_plan_phase_block_volatile_only() -> None:
    """AQ1: phase instructions are a separate block, not required to weld into system."""
    assert plan_phase_block(None) == ""
    planning = plan_phase_block("planning")
    executing = plan_phase_block("executing")
    assert "Plan phase (platform · planning)" in planning
    assert "Plan phase (platform · executing)" in executing
    assert "You are an agent." not in planning


def test_planning_allowlist_excludes_writes() -> None:
    assert "update_plan" in PLANNING_TOOL_ALLOWLIST
    assert "propose_patch" not in PLANNING_TOOL_ALLOWLIST
    assert "run_command" not in PLANNING_TOOL_ALLOWLIST
    assert "search_sources" not in PLANNING_TOOL_ALLOWLIST
    assert "read_file" not in PLANNING_TOOL_ALLOWLIST


@pytest.mark.asyncio
async def test_update_plan_planning_forces_pending() -> None:
    from app.tools.core import tools as core

    result = await core.update_plan(
        [
            {"title": "A", "status": "in_progress"},
            {"title": "B", "status": "done"},
        ],
        plan_phase="planning",
    )
    assert result["awaiting_consent"] is True
    assert all(i["status"] == "pending" for i in result["items"])



def test_writing_planning_scope() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    registry = build_registry()
    names = {s.name for s in tool_scope(profile, registry, plan_phase="planning")}
    assert names <= {"update_plan", "stub_echo"}
    assert "update_plan" in names
    assert "draft_section" not in names
    assert "propose_patch" not in names
    assert "search_sources" not in names
    assert "read_file" not in names


def test_agent_executing_waives_write_approvals() -> None:
    """After「按此执行」, Plan consent covers file edits — no per-edit gate."""
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("agent")
    registry = build_registry()

    normal = {s.name: s for s in tool_scope(profile, registry, plan_phase=None)}
    assert normal["edit_file"].requires_approval is True
    assert normal["write_file"].requires_approval is True

    executing = {s.name: s for s in tool_scope(profile, registry, plan_phase="executing")}
    assert executing["edit_file"].requires_approval is False
    assert executing["write_file"].requires_approval is False
    assert executing["propose_patch"].requires_approval is False
    # Shell stays gated — not implied by checklist consent.
    assert executing["run_command"].requires_approval is True


def test_executing_block_mentions_preauthorized_edits() -> None:
    block = plan_phase_block("executing")
    assert "pre-authorized" in block.lower() or "按此执行" in block
