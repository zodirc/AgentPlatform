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


def test_payload_schemas_are_valid_json_schema() -> None:
    index = json.loads((SCHEMAS_DIR / "_index.json").read_text(encoding="utf-8"))
    for schema_ref in index.get("properties", {}).values():
        schema_file = schema_ref["const"] if isinstance(schema_ref, dict) else schema_ref
        schema = json.loads((SCHEMAS_DIR / schema_file).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
