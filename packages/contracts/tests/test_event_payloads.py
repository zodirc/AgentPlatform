from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from validate_payload import indexed_event_types, resolve_schemas_dir, validate_event_payload

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "events"
SCHEMAS_DIR = resolve_schemas_dir()


def test_index_maps_to_existing_schema_files() -> None:
    index = json.loads((SCHEMAS_DIR / "_index.json").read_text(encoding="utf-8"))
    for event_type, schema_ref in index.get("properties", {}).items():
        schema_file = schema_ref["const"] if isinstance(schema_ref, dict) else schema_ref
        assert (SCHEMAS_DIR / schema_file).is_file(), f"missing schema for {event_type}"


def test_indexed_types_match_properties() -> None:
    index = json.loads((SCHEMAS_DIR / "_index.json").read_text(encoding="utf-8"))
    expected = {
        key
        for key, value in index.get("properties", {}).items()
        if isinstance(value, dict) and "const" in value
    }
    assert indexed_event_types(schemas_dir=SCHEMAS_DIR) == expected


@pytest.mark.parametrize("fixture_path", sorted(FIXTURES_DIR.glob("*.json")))
def test_fixture_payloads_validate(fixture_path: Path) -> None:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    validate_event_payload(data["type"], data["payload"], schemas_dir=SCHEMAS_DIR)


def test_write_file_approval_payload_allows_preview_fields() -> None:
    validate_event_payload(
        "approval.requested",
        {
            "tool_call_id": "call_1",
            "tool_name": "write_file",
            "arguments": {"path": "exports/dp.md", "content": "# DP"},
            "path": "exports/dp.md",
            "old_text": "",
            "new_text": "# DP",
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_write_file_tool_completed_allows_bytes_written() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_1",
            "tool_name": "write_file",
            "status": "ok",
            "summary": "Wrote exports/dp.md",
            "bytes_written": 1234,
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_edit_file_tool_completed_allows_impact_checks_meta() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_1",
            "tool_name": "edit_file",
            "status": "ok",
            "summary": "Edited mod.py; impact: 2 reference(s); checks: no new issues",
            "path": "mod.py",
            "old_text": "x = 1",
            "new_text": "x = 2",
            "bytes_written": 12,
            "applies": True,
            "impact": {
                "status": "ok",
                "symbol": "alpha",
                "reference_count": 2,
            },
            "checks": {
                "status": "ok",
                "syntax": "ok",
                "baseline_count": 0,
                "new_issue_count": 0,
            },
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_edit_file_tool_completed_allows_candidate_count() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_2",
            "tool_name": "edit_file",
            "status": "error",
            "summary": "old_text not found",
            "path": "mod.py",
            "applies": False,
            "candidate_count": 3,
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_edit_file_tool_completed_allows_related_tests_count() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_2b",
            "tool_name": "edit_file",
            "status": "ok",
            "summary": "Edited mod.py; related_tests: 2 path(s)",
            "path": "mod.py",
            "applies": True,
            "related_tests_count": 2,
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_read_file_tool_completed_allows_outline_count() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_2c",
            "tool_name": "read_file",
            "status": "ok",
            "summary": "Read big.py truncated",
            "path": "big.py",
            "truncated": True,
            "is_truncated": True,
            "outline_count": 12,
            "chars_read": 32000,
            "file_chars": 90000,
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_locate_tool_completed_allows_fuse_probe_meta() -> None:
    validate_event_payload(
        "tool.completed",
        {
            "tool_call_id": "call_3",
            "tool_name": "search_codebase",
            "status": "ok",
            "summary": "locate incomplete",
            "locate_mode": "symbol",
            "locate_incomplete": True,
            "definition_count": 0,
            "locate_status": "failed",
            "degraded_reason": "start_failed:RuntimeError",
            "locate_fuse_fail_reason": "lsp_failed",
            "candidates_from": "ast_index",
            "candidate_count": 2,
            "subagent_id": "sub-explore01",
        },
        schemas_dir=SCHEMAS_DIR,
    )


def test_terminal_turn_payloads_allow_post_turn_jobs() -> None:
    jobs = ["sources.index_sync"]
    validate_event_payload(
        "turn.completed",
        {
            "summary": "done",
            "termination_reason": "final",
            "post_turn_jobs": jobs,
        },
        schemas_dir=SCHEMAS_DIR,
    )
    validate_event_payload(
        "turn.failed",
        {
            "termination_reason": "fatal_error",
            "message": "boom",
            "post_turn_jobs": jobs,
        },
        schemas_dir=SCHEMAS_DIR,
    )
    validate_event_payload(
        "turn.cancelled",
        {"reason": "user_requested", "post_turn_jobs": jobs},
        schemas_dir=SCHEMAS_DIR,
    )


def test_payload_schemas_are_valid_json_schema() -> None:
    index = json.loads((SCHEMAS_DIR / "_index.json").read_text(encoding="utf-8"))
    for schema_ref in index.get("properties", {}).values():
        schema_file = schema_ref["const"] if isinstance(schema_ref, dict) else schema_ref
        schema = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
