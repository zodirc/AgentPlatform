from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = ROOT / "eval" / "golden"
SCHEMA_PATH = ROOT / "packages" / "contracts" / "eval" / "golden_turn.schema.json"


@pytest.fixture(scope="module")
def golden_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.mark.parametrize("path", sorted(GOLDEN_DIR.rglob("*.yaml")))
def test_golden_case_matches_schema(path: Path, golden_validator: Draft202012Validator) -> None:
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    golden_validator.validate(case)
