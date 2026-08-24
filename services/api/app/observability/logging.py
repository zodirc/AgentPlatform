"""统一 JSON 结构化日志（structlog + stdlib 桥接，B23）。

业务代码多用 ``logging.getLogger``；通过 ``ProcessorFormatter`` 桥接保证
timestamp、JSON、request/turn 关联字段一致输出。
"""

from __future__ import annotations
import logging
import sys

import structlog


def configure_logging(*, service: str, level: str = "INFO") -> None:
    """配置 structlog 与 root logger 共用 JSON 输出管道。

    参数:
        service: 写入 contextvars 的服务名（如 ``agent-api``）。
        level: 日志级别字符串（默认 INFO）。

    返回:
        无。
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

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
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(log_level)

    structlog.contextvars.bind_contextvars(service=service)
