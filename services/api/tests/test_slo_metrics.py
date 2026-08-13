"""SLO baseline metric helpers (O11 / WP0-b)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.observability import slo
from app.observability.metrics import metrics


def test_turn_ttfb_observes_once() -> None:
    turn_id = uuid4()
    slo.mark_turn_accepted_at_api(turn_id)
    slo.observe_turn_accepted(turn_id)
    # Second call is a no-op (already popped).
    slo.observe_turn_accepted(turn_id)
    rendered = metrics.render_prometheus()
    assert "turn_ttfb_seconds" in rendered


def test_event_pipeline_lag_observes() -> None:
    past = datetime.now(timezone.utc) - timedelta(milliseconds=50)
    slo.observe_event_pipeline_lag(past)
    slo.observe_event_pipeline_lag(past.isoformat())
    rendered = metrics.render_prometheus()
    assert "event_pipeline_lag_seconds" in rendered
