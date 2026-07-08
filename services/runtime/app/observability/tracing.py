from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing(*, service_name: str, enabled: bool) -> None:
    if not enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.warning("OpenTelemetry packages not installed; tracing disabled")
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
            logger.info("OpenTelemetry OTLP exporter enabled: %s", otlp_endpoint)
        except ImportError:
            logger.warning("OTLP exporter not installed; falling back to console spans")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry tracing enabled for %s", service_name)


def instrument_fastapi(app, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed")
        return
    FastAPIInstrumentor.instrument_app(app)
