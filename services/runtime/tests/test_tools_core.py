from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.engine.state import TurnState
from app.graph.runner import run_via_langgraph
from app.scenarios.registry import ScenarioRegistry
from app.tools.core import tools as core


@pytest.mark.asyncio
async def test_run_command_simulate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "run_command_mode", "simulate")
    result = await core.run_command("echo hi")
    assert result["status"] == "executed"
    assert "[simulated]" in result["stdout"]


@pytest.mark.asyncio
async def test_glob_lists_workspace_files(workspace: Path) -> None:
    (workspace / "notes.md").write_text("hello", encoding="utf-8")
    (workspace / "skip.txt").write_text("x", encoding="utf-8")

    result = await core.glob("*.md")

    assert result["match_count"] == 1
    assert result["matches"] == ["notes.md"]


@pytest.mark.asyncio
async def test_draft_section_writes_revisions_path(workspace: Path) -> None:
    result = await core.draft_section("intro", "# Intro\n")

    assert result["status"] == "drafted"
    assert result["path"] == ".agent/revisions/intro.md"
    assert (workspace / ".agent" / "revisions" / "intro.md").read_text(encoding="utf-8") == "# Intro\n"


@pytest.mark.asyncio
async def test_edit_file_replaces_once(workspace: Path) -> None:
    target = workspace / "doc.md"
    target.write_text("alpha beta gamma", encoding="utf-8")

    result = await core.edit_file("doc.md", "beta", "BETA")

    assert result["status"] == "edited"
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma"


@pytest.mark.asyncio
async def test_export_document_from_revisions(workspace: Path) -> None:
    rev = workspace / ".agent" / "revisions"
    rev.mkdir(parents=True)
    (rev / "body.md").write_text("Section body", encoding="utf-8")
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document("exports/out.md")

    assert result["output_path"] == "exports/out.md"
    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert "# Title" in exported
    assert "Section body" in exported


def test_scenario_registry_loads_profiles() -> None:
    ScenarioRegistry.load()
    writing = ScenarioRegistry.get("writing")
    agent = ScenarioRegistry.get("agent")
    interview = ScenarioRegistry.get("interview")

    assert writing.scenario_id == "writing"
    assert "draft_section" in writing.tool_names
    assert agent.scenario_id == "agent"
    assert "glob" in agent.tool_names
    assert interview.scenario_id == "interview"
    assert writing.system_prompt
    assert agent.system_prompt
    assert "Never guess file paths" in agent.system_prompt
    assert "Do not repeat the same tool call" in agent.system_prompt


@pytest.mark.asyncio
async def test_run_via_langgraph_delegates_to_engine() -> None:
    engine = MagicMock()
    engine.run = AsyncMock(return_value="completed")
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
    )

    result = await run_via_langgraph(engine, state)

    assert result == "completed"
    engine.run.assert_awaited_once_with(state)
