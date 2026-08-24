"""Starlette 中间件：解析/生成 ``X-Request-ID`` 并绑定 structlog 上下文。"""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.request_context_vars import set_request_id

REQUEST_ID_HEADER = "X-Request-ID"


def _parse_request_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """作用：每个 HTTP 请求入口绑定 ``request_id`` 并回写响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        """作用：解析请求 ID、清理/绑定 structlog contextvars、透传下游。

        参数：
            request: Starlette 请求。
            call_next: 下一层 ASGI 处理器。

        返回：
            附带 ``X-Request-ID`` 响应头的 Response。
        """
        raw = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = _parse_request_id(raw) if raw else uuid4()
        request.state.request_id = request_id
        set_request_id(request_id)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            service="agent-runtime",
            request_id=str(request_id),
        )

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = str(request_id)
        return response
