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
    async def dispatch(self, request: Request, call_next) -> Response:
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
