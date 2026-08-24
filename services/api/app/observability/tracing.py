"""OpenTelemetry 追踪初始化与 FastAPI 自动埋点。

可选启用：未安装 OTel 包或 ``enabled=False`` 时静默跳过；
支持 OTLP HTTP exporter 或控制台 fallback。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing(*, service_name: str, enabled: bool) -> None:
    """安装全局 ``TracerProvider`` 与 span exporter。

    参数:
        service_name: OTel ``service.name`` 资源属性。
        enabled: False 时直接返回。

    返回:
        无。

    异常:
        无；ImportError 时打 warning 并禁用追踪。
    """
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
    """为 FastAPI 应用注册 HTTP 服务端 span  instrumentation。

    参数:
        app: FastAPI/Starlette 应用实例。
        enabled: False 时跳过。

    返回:
        无。
    """
    if not enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed")
        return
    FastAPIInstrumentor.instrument_app(app)
