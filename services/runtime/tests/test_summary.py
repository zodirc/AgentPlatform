from __future__ import annotations

from app.context.summary import (
    StructuredSummary,
    build_context_summary_record,
    parse_structured_summary_text,
    structured_summary_from_messages,
    structured_summary_from_turn_rows,
)
from app.engine.state import assistant_text, user_message


def test_structured_summary_from_messages_extracts_task_and_files() -> None:
    summary = structured_summary_from_messages(
        [
            user_message("update @sections/01.md outline"),
            assistant_text("expanded section one with details"),
        ]
    )
    assert "sections/01.md" in summary.files_touched
    assert "outline" in summary.task


def test_structured_summary_from_turn_rows() -> None:
    summary = structured_summary_from_turn_rows(
        [
            {
                "user_input": "read README.md",
                "latest_output": "Updated docs/README.md section",
            }
        ]
    )
    assert "README.md" in summary.files_touched or "docs/README.md" in summary.files_touched


def test_parse_structured_summary_text_roundtrip() -> None:
    original = StructuredSummary(
        task="refactor panels",
        files_touched=["AgentPanels.tsx"],
        decisions=["use three columns"],
        open_items=["add tests"],
        narrative="refactored layout",
    )
    parsed = parse_structured_summary_text(original.to_autocompact_text())
    assert parsed is not None
    assert parsed.task == "refactor panels"
    assert parsed.files_touched == ["AgentPanels.tsx"]


def test_build_context_summary_record_includes_structured_fields() -> None:
    summary = StructuredSummary(task="write docs", narrative="done")
    record = build_context_summary_record(
        summary,
        last_turn_id="t1",
        last_status="completed",
        turn_count=3,
        source="manual_compact",
    )
    assert record["task"] == "write docs"
    assert record["source"] == "manual_compact"
    assert record["turn_count"] == 3
