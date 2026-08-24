"""structlog + stdlib 统一 JSON 日志管道（B23 ProcessorFormatter 桥接）。"""

from __future__ import annotations


import logging
import sys

import structlog


def configure_logging(*, service: str, level: str = "INFO") -> None:
    """作用：统一 structlog+stdlib JSON 日志与脱敏 processor。"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    from app.privacy.redact import redact_log_event

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_log_event,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(log_level)

    structlog.contextvars.bind_contextvars(service=service)
