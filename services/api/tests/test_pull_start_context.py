"""Pull start context: pull_eligible + plan_phase helpers."""

from __future__ import annotations

from app.services.resource.turns import _normalize_plan_phase, resolve_pull_eligible


def test_resolve_pull_eligible_ops_never_claimable() -> None:
    assert resolve_pull_eligible(dispatch_notify=False) is False
    assert resolve_pull_eligible(dispatch_notify=False, pull_eligible=True) is False
    assert resolve_pull_eligible(dispatch_notify=True) is True
    assert resolve_pull_eligible(dispatch_notify=True, pull_eligible=False) is False


def test_normalize_plan_phase() -> None:
    assert _normalize_plan_phase(None) is None
    assert _normalize_plan_phase("planning") == "planning"
    assert _normalize_plan_phase("EXECUTING") == "executing"
    assert _normalize_plan_phase("ready") is None


def test_normalize_model_mode() -> None:
    from app.services.resource.turns import _normalize_model_mode

    assert _normalize_model_mode("LIVE") == "live"
    assert _normalize_model_mode("nope") is None
