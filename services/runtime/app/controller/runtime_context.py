from __future__ import annotations

from contextvars import ContextVar
from typing import Awaitable, Callable

EventWriter = Callable[..., Awaitable[None]]

_event_writer: ContextVar[EventWriter | None] = ContextVar("event_writer", default=None)


def set_event_writer(writer: EventWriter | None) -> None:
    _event_writer.set(writer)


def get_event_writer() -> EventWriter | None:
    return _event_writer.get()
