"""Validate turn_events payloads against ADR-017 JSON Schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SCHEMAS_DIR = _REPO_ROOT / "packages" / "contracts" / "schemas" / "events" / "payloads"


class EventPayloadValidationError(Exception):
    def __init__(self, event_type: str, errors: list[str]) -> None:
        self.event_type = event_type
        self.errors = errors
        detail = "; ".join(errors) if errors else "invalid payload"
        super().__init__(f"{event_type}: {detail}")


def resolve_schemas_dir() -> Path:
    import os

    override = os.environ.get("EVENT_PAYLOAD_SCHEMAS_DIR")
    if override:
        return Path(override)
    docker = Path("/app/contracts/events/payloads")
    if docker.is_dir():
        return docker
    return _DEFAULT_SCHEMAS_DIR


@lru_cache(maxsize=1)
def _load_index(schemas_dir: str) -> dict[str, str]:
    index_path = Path(schemas_dir) / "_index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    mapped: dict[str, str] = {}
    for event_type, value in data.get("properties", {}).items():
        if isinstance(value, str):
            mapped[event_type] = value
        elif isinstance(value, dict) and isinstance(value.get("const"), str):
            mapped[event_type] = value["const"]
    return mapped


@lru_cache(maxsize=32)
def _validator(schema_file: str, schemas_dir: str) -> Draft202012Validator | None:
    path = Path(schemas_dir) / schema_file
    if not path.is_file():
        return None
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_event_payload(event_type: str, payload: dict[str, Any], *, schemas_dir: Path | None = None) -> None:
    root = schemas_dir or resolve_schemas_dir()
    index = _load_index(str(root))
    schema_file = index.get(event_type)
    if schema_file is None:
        return
    validator = _validator(schema_file, str(root))
    if validator is None:
        return
    errors = sorted({e.message for e in validator.iter_errors(payload)})
    if errors:
        raise EventPayloadValidationError(event_type, errors)


def indexed_event_types(*, schemas_dir: Path | None = None) -> set[str]:
    root = schemas_dir or resolve_schemas_dir()
    return set(_load_index(str(root)).keys())
