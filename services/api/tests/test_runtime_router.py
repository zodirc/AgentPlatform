from __future__ import annotations

import json

import pytest

from app.services.command.runtime_router import RuntimeRouter, _parse_url_map


def test_parse_url_map_empty() -> None:
    assert _parse_url_map("") == {}
    assert _parse_url_map("   ") == {}


def test_parse_url_map_object() -> None:
    raw = json.dumps({"runtime-a": "http://runtime-a:8001", "runtime-b": "http://runtime-b:8001/"})
    assert _parse_url_map(raw) == {
        "runtime-a": "http://runtime-a:8001",
        "runtime-b": "http://runtime-b:8001",
    }


def test_url_for_runner_and_round_robin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import Settings

    configured = Settings(
        runtime_url="http://runtime:8001",
        runtime_url_map=json.dumps(
            {"runtime-a": "http://runtime-a:8001", "runtime-b": "http://runtime-b:8001"}
        ),
    )
    monkeypatch.setattr("app.services.command.runtime_router.settings", configured)
    router = RuntimeRouter()

    assert router.url_for_runner("runtime-b") == "http://runtime-b:8001"
    assert router.url_for_runner(None) == "http://runtime:8001"
    first = router.url_for_new_turn()
    second = router.url_for_new_turn()
    assert {first, second} == {"http://runtime-a:8001", "http://runtime-b:8001"}
    assert first != second
