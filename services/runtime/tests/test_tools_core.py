from __future__ import annotations

import json
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
async def test_draft_section_writes_monofile_manuscript(workspace: Path) -> None:
    turn_id = uuid4()
    session_id = uuid4()
    result = await core.draft_section(
        "intro", "# Intro\n", turn_id=turn_id, session_id=session_id
    )

    assert result["status"] == "drafted"
    assert result["path"] == ".agent/work/drafts/manuscript.md"
    assert result["layout"] == "monofile"
    text = (workspace / result["path"]).read_text(encoding="utf-8")
    assert "<!-- section:intro -->" in text
    assert "# Intro" in text
    manifest = workspace / ".agent" / "work" / "turns" / f"{turn_id}.json"
    assert '"intro"' in manifest.read_text(encoding="utf-8")
    history = workspace / ".agent" / "work" / "history" / "intro" / f"{turn_id}.md"
    assert history.is_file()


@pytest.mark.asyncio
async def test_draft_section_appends_chapters_same_file(workspace: Path) -> None:
    await core.draft_section("ch1", "v1", turn_id=uuid4(), session_id=uuid4())
    await core.draft_section("ch2", "v2", turn_id=uuid4(), session_id=uuid4())
    await core.draft_section("ch1", "v1b", turn_id=uuid4(), session_id=uuid4())
    path = workspace / ".agent" / "work" / "drafts" / "manuscript.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("<!-- section:ch1 -->") == 1
    assert "v1b" in text and "v2" in text


@pytest.mark.asyncio
async def test_draft_section_sections_layout_opt_in(workspace: Path) -> None:
    turn_id = uuid4()
    result = await core.draft_section(
        "intro", "# Intro\n", turn_id=turn_id, layout="sections"
    )
    assert result["path"] == ".agent/work/drafts/intro.md"
    assert (workspace / result["path"]).read_text(encoding="utf-8") == "# Intro\n"


@pytest.mark.asyncio
async def test_export_document_reads_work_scoped_drafts(workspace: Path) -> None:
    turn_id = uuid4()
    session_id = uuid4()
    await core.draft_section("body", "Session body", turn_id=turn_id, session_id=session_id)
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["body"],
        source="current_draft",
        output_path="exports/out.md",
        turn_id=turn_id,
        session_id=session_id,
    )

    assert result["delivery_status"] == "ok"
    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert "Session body" in exported


@pytest.mark.asyncio
async def test_export_document_legacy_session_revision_compat(workspace: Path) -> None:
    """Old session-scoped revisions still export when listed in a legacy manifest."""
    turn_id = uuid4()
    session_id = uuid4()
    legacy_rel = f".agent/sessions/{session_id}/revisions/{turn_id}/body.md"
    legacy = workspace / legacy_rel
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("Legacy session body", encoding="utf-8")
    man = (
        workspace
        / ".agent"
        / "sessions"
        / str(session_id)
        / "turns"
        / str(turn_id)
        / "manifest.json"
    )
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(
        json.dumps(
            {
                "turn_id": str(turn_id),
                "session_id": str(session_id),
                "sections": ["body"],
                "revisions": {"body": legacy_rel},
            }
        ),
        encoding="utf-8",
    )
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["body"],
        source="current_draft",
        output_path="exports/out.md",
        turn_id=turn_id,
        session_id=session_id,
    )

    assert result["delivery_status"] == "ok"
    assert "Legacy session body" in (workspace / "exports" / "out.md").read_text(
        encoding="utf-8"
    )

@pytest.mark.asyncio
async def test_export_document_flat_legacy_revision_fallback(workspace: Path) -> None:
    turn_id = uuid4()
    legacy = workspace / ".agent" / "revisions" / "body.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("Legacy body", encoding="utf-8")
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["body"],
        source="current_draft",
        output_path="exports/out.md",
        turn_id=turn_id,
        session_id=uuid4(),
    )

    assert result["delivery_status"] == "warning"
    assert "legacy" in " ".join(result["delivery_issues"]).lower()
    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert "Legacy body" in exported


@pytest.mark.asyncio
async def test_edit_file_replaces_once(workspace: Path) -> None:
    target = workspace / "doc.md"
    target.write_text("alpha beta gamma", encoding="utf-8")

    result = await core.edit_file("doc.md", "beta", "BETA")

    assert result["status"] == "edited"
    assert target.read_text(encoding="utf-8") == "alpha BETA gamma"


@pytest.mark.asyncio
async def test_export_document_from_revisions(workspace: Path) -> None:
    turn_id = uuid4()
    await core.draft_section("body", "Section body", turn_id=turn_id)
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["body"],
        source="current_draft",
        output_path="exports/out.md",
        turn_id=turn_id,
    )

    assert result["output_path"] == "exports/out.md"
    assert result["delivery_status"] == "ok"
    assert result["included_sections"] == ["body"]
    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert "# Title" in exported
    assert "Section body" in exported


@pytest.mark.asyncio
async def test_export_document_prefers_revisions_over_sections(workspace: Path) -> None:
    turn_id = uuid4()
    await core.draft_section("ch1", "Chapter one draft", turn_id=turn_id)
    sections = workspace / "sections"
    sections.mkdir()
    (sections / "stale.md").write_text("old junk", encoding="utf-8")
    (workspace / "outline.md").write_text("# Outline", encoding="utf-8")

    await core.export_document(
        section_ids=["ch1"],
        source="current_draft",
        output_path="exports/out.md",
        turn_id=turn_id,
    )

    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert "Chapter one draft" in exported
    assert "old junk" not in exported


@pytest.mark.asyncio
async def test_export_document_reads_only_explicit_confirmed_sections(workspace: Path) -> None:
    sections = workspace / "sections"
    sections.mkdir()
    (sections / "one.md").write_text("First", encoding="utf-8")
    (sections / "two.md").write_text("Second", encoding="utf-8")
    (sections / "junk.md").write_text("Historical junk", encoding="utf-8")

    result = await core.export_document(
        section_ids=["two", "one"],
        source="confirmed",
        output_path="exports/out.md",
    )

    assert result["delivery_status"] == "ok"
    exported = (workspace / "exports" / "out.md").read_text(encoding="utf-8")
    assert exported.index("Second") < exported.index("First")
    assert "Historical junk" not in exported


@pytest.mark.asyncio
async def test_export_document_does_not_write_partial_output(workspace: Path) -> None:
    sections = workspace / "sections"
    sections.mkdir()
    (sections / "one.md").write_text("First", encoding="utf-8")

    result = await core.export_document(
        section_ids=["one", "missing"],
        source="confirmed",
        output_path="exports/out.md",
    )

    assert result["delivery_status"] == "failed"
    assert result["missing_sections"] == ["missing"]
    assert not (workspace / "exports" / "out.md").exists()


@pytest.mark.asyncio
async def test_export_document_requires_explicit_scope(workspace: Path) -> None:
    result = await core.export_document(output_path="exports/out.md")

    assert result["delivery_status"] == "failed"
    assert not (workspace / "exports" / "out.md").exists()


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
    assert "search_sources" in writing.system_prompt
    assert "[cite:xxx]" in writing.system_prompt
    assert "Never omit `section_ids`" in writing.system_prompt
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
