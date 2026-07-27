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
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
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
