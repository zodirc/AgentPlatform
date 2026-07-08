from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.observability.metrics import (
    metrics,
    record_stall_detected,
    record_step_duration,
    record_tool_call,
    record_turn_finished,
)
from app.observability.tracing import instrument_fastapi, setup_tracing


def test_metrics_registry_render() -> None:
    metrics.inc("demo_total", scenario_id="writing")
    metrics.set_gauge("demo_gauge", 2.5, scenario_id="writing")
    metrics.observe("demo_hist", 0.1, scenario_id="writing")
    metrics.observe("demo_hist", 0.3, scenario_id="writing")

    body = metrics.render_prometheus()
    assert "demo_total" in body
    assert "demo_gauge" in body
    assert "demo_hist_sum" in body
    assert "demo_hist_count" in body


def test_record_helpers() -> None:
    record_turn_finished(
        scenario_id="agent",
        status="completed",
        steps=2,
        duration_seconds=1.5,
        termination_reason="model_timeout",
        input_tokens=10,
        output_tokens=5,
    )
    record_tool_call(tool_name="grep", status="ok")
    record_step_duration(scenario_id="writing", duration_seconds=0.2)
    record_stall_detected(scenario_id="writing")
    assert metrics.render_prometheus()


def test_tracing_console_exporter() -> None:
    with patch.dict("os.environ", {}, clear=True):
        setup_tracing(service_name="runtime-test", enabled=True)
    instrument_fastapi(MagicMock(), enabled=True)


def test_tracing_otlp_exporter() -> None:
    with patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces"}):
        setup_tracing(service_name="runtime-test", enabled=True)
