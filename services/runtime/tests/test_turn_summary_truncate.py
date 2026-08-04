"""INFRA-1: turn.completed summary clamp to schema maxLength."""

from __future__ import annotations

from app.controller.turn_controller import (
    _TURN_COMPLETED_SUMMARY_MAX,
    _truncate_turn_summary,
)


def test_truncate_turn_summary_passthrough() -> None:
    assert _truncate_turn_summary("ok") == "ok"
    assert _truncate_turn_summary(None) == ""
    assert _truncate_turn_summary("x" * _TURN_COMPLETED_SUMMARY_MAX) == (
        "x" * _TURN_COMPLETED_SUMMARY_MAX
    )


def test_truncate_turn_summary_clamps_with_ellipsis() -> None:
    long = "a" * (_TURN_COMPLETED_SUMMARY_MAX + 50)
    out = _truncate_turn_summary(long)
    assert len(out) == _TURN_COMPLETED_SUMMARY_MAX
    assert out.endswith("…")
    assert out[:-1] == "a" * (_TURN_COMPLETED_SUMMARY_MAX - 1)
