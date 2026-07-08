from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.observability.tracing import instrument_fastapi, setup_tracing


def test_tracing_disabled_is_noop() -> None:
    setup_tracing(service_name="test-api", enabled=False)
    instrument_fastapi(object(), enabled=False)


def test_tracing_console_exporter() -> None:
    with patch.dict("os.environ", {}, clear=True):
        setup_tracing(service_name="test-api", enabled=True)
    instrument_fastapi(MagicMock(), enabled=True)


def test_tracing_otlp_exporter() -> None:
    with patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces"}):
        setup_tracing(service_name="test-api", enabled=True)
