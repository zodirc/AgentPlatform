from __future__ import annotations

from app.engine.agent_engine import _compact_edit_file_event_meta


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
