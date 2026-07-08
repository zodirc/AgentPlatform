from __future__ import annotations

from app.observability.metrics import MetricsRegistry


def test_metrics_gauge_render() -> None:
    reg = MetricsRegistry()
    reg.inc("sse_reconnect_total")
    reg.inc("sse_reconnect_total", scenario_id="writing")
    reg.set_gauge("projection_lag_seconds", 0.42)
    body = reg.render_prometheus()
    assert "sse_reconnect_total 1.0" in body
    assert 'scenario_id="writing"' in body
    assert "projection_lag_seconds 0.42" in body
