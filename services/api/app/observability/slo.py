"""SLO baseline histograms (backend-scaling O11 / WP0-b).

``turn_ttfb_seconds``: wall time from StartTurn accept (202 path) until the
api first observes ``turn.accepted`` (listener / SSE fetch side).

``event_pipeline_lag_seconds``: ``turn_events.ts`` → SSE/WS flush moment.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID

from cachetools import TTLCache

from app.observability.metrics import metrics

# Bound memory: finished turns stop being waited on well within the TTL.
_ttfb_starts: TTLCache = TTLCache(maxsize=8192, ttl=600)


def mark_turn_accepted_at_api(turn_id: UUID) -> None:
    """Record StartTurn accept moment (call only when HTTP will return 202)."""
    _ttfb_starts[turn_id] = time.monotonic()


def observe_turn_accepted(turn_id: UUID) -> None:
    """Observer when ``turn.accepted`` is first visible on the api event path."""
    started = _ttfb_starts.pop(turn_id, None)
    if started is None:
        return
    metrics.observe("turn_ttfb_seconds", max(0.0, time.monotonic() - started))


def observe_event_pipeline_lag(event_ts: datetime | str | None) -> None:
    """Record lag from event timestamp to SSE/WS flush."""
    if event_ts is None:
        return
    try:
        if isinstance(event_ts, str):
            raw = event_ts.replace("Z", "+00:00")
            ts = datetime.fromisoformat(raw)
        else:
            ts = event_ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        lag = (datetime.now(timezone.utc) - ts).total_seconds()
        if lag >= 0:
            metrics.observe("event_pipeline_lag_seconds", lag)
    except Exception:
        return
