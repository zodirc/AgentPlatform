from __future__ import annotations

import sys
from pathlib import Path

from app.engine.agent_engine import (
    _compact_edit_file_event_meta,
    _compact_locate_event_meta,
    _tool_completed_base,
)


def _contracts_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "packages" / "contracts"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("packages/contracts not found")


def test_compact_edit_file_event_meta_success() -> None:
    meta = _compact_edit_file_event_meta(
        {
            "applies": True,
            "impact": {
                "status": "ok",
                "symbol": "alpha",
                "references": [{"path": "a.py"}, {"path": "b.py"}],
                "reference_count": 2,
            },
            "checks": {
                "status": "ok",
                "syntax": "ok",
                "baseline_count": 1,
                "new_issues": [{"message": "x"}],
            },
        }
    )
    assert meta["applies"] is True
    assert meta["impact"] == {
        "status": "ok",
        "symbol": "alpha",
        "reference_count": 2,
    }
    assert meta["checks"] == {
        "status": "ok",
        "syntax": "ok",
        "baseline_count": 1,
        "new_issue_count": 1,
    }
    # Full refs/issues must not leak onto the event bus projection.
    assert "references" not in meta["impact"]
    assert "new_issues" not in meta["checks"]


def test_compact_edit_file_event_meta_span_miss() -> None:
    meta = _compact_edit_file_event_meta(
        {
            "applies": False,
            "error": "old_text not found",
            "candidates": [{"line": 1}, {"line": 2}, {"line": 3}],
        }
    )
    assert meta["applies"] is False
    assert meta["candidate_count"] == 3


def test_search_codebase_tool_completed_fuse_meta_validates() -> None:
    """agent.05 / collab.01: explore→search_codebase emits fuse probe fields.

    origin/master shipped ``locate_fuse_fail_reason`` on the event bus before the
    tool.completed schema allowed it → EventPayloadValidationError → turn.failed
    mid-tool (tool.started then turn.failed, no subagent.completed).
    """
    contracts = _contracts_dir()
    if str(contracts) not in sys.path:
        sys.path.insert(0, str(contracts))
    from validate_payload import validate_event_payload

    result = {
        "mode": "symbol",
        "locate_incomplete": True,
        "definitions": [],
        "status": "failed",
        "degraded_reason": "start_failed:RuntimeError",
        "locate_fuse_fail_reason": "lsp_failed",
        "candidates": [{"path": "a.py", "line": 1}, {"path": "b.py", "line": 2}],
        "candidates_from": "ast_index",
        "summary": (
            "search_codebase: language server required for symbol locate "
            "(start_failed:RuntimeError); fix runtime provider"
        ),
    }
    payload = _tool_completed_base(
        tool_call_id="search_codebase-deadbeef",
        tool_name="search_codebase",
        status="ok",
        summary=result["summary"],
        **_compact_locate_event_meta(result),
    )
    payload["subagent_id"] = "sub-explore01"
    assert payload["locate_fuse_fail_reason"] == "lsp_failed"
    assert payload["candidates_from"] == "ast_index"
    assert payload["candidate_count"] == 2
    validate_event_payload("tool.completed", payload, schemas_dir=contracts / "schemas" / "events" / "payloads")
