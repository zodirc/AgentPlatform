"""Keep externally published command schemas aligned with Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from agent_contracts.commands import ModelOverride, StartTurnCommand

ROOT = Path(__file__).resolve().parents[3]
START_TURN_SCHEMA = (
    ROOT / "packages" / "contracts" / "schemas" / "commands" / "start_turn.json"
)


def test_start_turn_json_schema_covers_pydantic_fields() -> None:
    """Optional fields remain optional; no Pydantic fields are intentionally omitted."""
    schema = json.loads(START_TURN_SCHEMA.read_text(encoding="utf-8"))

    _assert_model_is_covered(StartTurnCommand, schema)
    _assert_model_is_covered(ModelOverride, schema["properties"]["model_override"])


def _assert_model_is_covered(model: type[StartTurnCommand | ModelOverride], schema: dict) -> None:
    fields = model.model_fields
    assert set(fields) <= set(schema["properties"])
    assert {name for name, field in fields.items() if field.is_required()} <= set(
        schema["required"]
    )
