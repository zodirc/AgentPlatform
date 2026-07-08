from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

_request_id: ContextVar[UUID | None] = ContextVar("request_id", default=None)


def get_request_id() -> UUID | None:
    return _request_id.get()


def set_request_id(value: UUID) -> None:
    _request_id.set(value)
