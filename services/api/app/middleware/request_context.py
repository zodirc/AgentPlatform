"""HTTP 请求上下文中间件（request_id、结构化日志、延迟指标）。

为每个入站请求分配或解析 ``X-Request-ID``，绑定 structlog 上下文，并在响应头回写；
同时按路由模板记录 ``http_request_duration_seconds``（B24 有界基数）。
"""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.context import set_request_id
from app.observability.metrics import metrics

REQUEST_ID_HEADER = "X-Request-ID"


def _parse_request_id(raw: str) -> UUID:
    """解析客户端传入的 request_id；非法时生成新 UUID。

    参数:
        raw: ``X-Request-ID`` 头原始字符串。

    返回:
        合法 UUID 或新生成的 uuid4。
    """
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Starlette 中间件：贯穿 request_id 与 HTTP 延迟观测。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        """处理单次 HTTP 请求：绑定上下文、计时、回写头。

        参数:
            request: Starlette 请求。
            call_next: 下游 ASGI 调用链。

        返回:
            带 ``X-Request-ID`` 的响应。

        异常:
            下游路由/处理器抛出的异常原样向上传播。
        """
        raw = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = _parse_request_id(raw) if raw else uuid4()
        request.state.request_id = request_id
        set_request_id(request_id)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            service="agent-api",
            request_id=str(request_id),
        )

        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = str(request_id)
        # B24: HTTP latency by route template (bounded cardinality — never the
        # raw path, which embeds UUIDs).
        route = request.scope.get("route")
        template = getattr(route, "path", None)
        if template:
            metrics.observe(
                "http_request_duration_seconds",
                time.perf_counter() - started,
                method=request.method,
                path=template,
                status=str(response.status_code),
            )
        return response
