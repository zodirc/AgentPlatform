"""Validate durable vs live TurnEvent envelopes against envelope.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "schemas" / "events"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "envelopes"


def _validator() -> Draft202012Validator:
    envelope = json.loads((EVENTS / "envelope.json").read_text(encoding="utf-8"))
    types = json.loads((EVENTS / "types.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        [
            (envelope["$id"], Resource.from_contents(envelope)),
            (types["$id"], Resource.from_contents(types)),
        ]
    )
    return Draft202012Validator(envelope, registry=registry)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")))
def test_envelope_fixtures(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    _validator().validate(data)


def test_live_requires_null_sequence() -> None:
    v = _validator()
    bad = json.loads((FIXTURES / "live.turn.token.json").read_text(encoding="utf-8"))
    bad["sequence"] = 1
    with pytest.raises(Exception):
        v.validate(bad)


def test_durable_rejects_null_sequence() -> None:
    v = _validator()
    bad = json.loads(
        (FIXTURES / "durable.turn.accepted.json").read_text(encoding="utf-8")
    )
    bad["sequence"] = None
    with pytest.raises(Exception):
        v.validate(bad)
