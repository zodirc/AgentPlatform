from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.tools.core import tools as core
from app.writing.export_lint import lint_export_markdown


def test_lint_detects_heading_skip_and_html() -> None:
    body = "# Title\n\n### Skipped\n\nhello <b>x</b>\n"
    issues = lint_export_markdown(body, profile="novel-zh")
    codes = {i.code for i in issues}
    assert "heading_skip" in codes
    assert "html_forbidden" in codes


def test_lint_empty_section_for_section_ids() -> None:
    body = "# Title\n\n## ch1\n\n\n## ch2\n\ntext\n"
    issues = lint_export_markdown(body, profile="novel-zh", section_ids=["ch1", "ch2"])
    assert any(i.code == "empty_section" and "ch1" in i.message for i in issues)


def test_lint_section_ids_allows_body_starting_with_heading() -> None:
    """export_document wraps ``## {id}``; bodies often open with their own H1/H2."""
    body = (
        "## shentou-outline\n\n"
        "<!-- section:shentou-outline -->\n"
        "# 《渗透》大纲\n\n"
        "intro\n\n"
        "<!-- /section:shentou-outline -->\n\n"
        "## 渗透-大纲\n\n"
        "# 《渗透》—— 电视剧大纲\n\n"
        "## 基本信息\n\n"
        "- 剧名：渗透\n"
    )
    issues = lint_export_markdown(
        body, profile="novel-zh", section_ids=["shentou-outline", "渗透-大纲"]
    )
    assert not any(i.code == "empty_section" for i in issues)


@pytest.mark.asyncio
async def test_export_document_ok_when_section_opens_with_h1(workspace: Path) -> None:
    turn_id = uuid4()
    await core.draft_section(
        "渗透-大纲",
        "# 《渗透》—— 电视剧大纲\n\n## 基本信息\n\n- 剧名：渗透\n",
        turn_id=turn_id,
    )
    (workspace / "outline.md").write_text("# Workspace outline\n\nnote\n", encoding="utf-8")

    result = await core.export_document(
        section_ids=["渗透-大纲"],
        source="current_draft",
        output_path="exports/shentou.md",
        profile="novel-zh",
        turn_id=turn_id,
    )
    assert result["delivery_status"] == "ok", result
    assert (workspace / "exports" / "shentou.md").exists()


@pytest.mark.asyncio
async def test_export_document_fails_structure_lint(workspace: Path) -> None:
    sections = workspace / "sections"
    sections.mkdir()
    (sections / "one.md").write_text("Hello <div>x</div>", encoding="utf-8")
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["one"],
        source="confirmed",
        output_path="exports/out.md",
        profile="novel-zh",
    )
    assert result["delivery_status"] == "failed"
    assert any("html_forbidden" in issue for issue in result["delivery_issues"])
    assert not (workspace / "exports" / "out.md").exists()


@pytest.mark.asyncio
async def test_export_document_profile_none_skips_html_rule(workspace: Path) -> None:
    turn_id = uuid4()
    await core.draft_section("body", "Section with <em>html</em>", turn_id=turn_id)
    (workspace / "outline.md").write_text("# Title", encoding="utf-8")

    result = await core.export_document(
        section_ids=["body"],
        source="current_draft",
        output_path="exports/out.md",
        profile="none",
        turn_id=turn_id,
    )
    assert result["delivery_status"] == "ok"
    assert (workspace / "exports" / "out.md").exists()
