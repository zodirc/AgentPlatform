"""Turn 内事件写回器的 ContextVar 绑定。

Engine / 工具侧通过 get_event_writer 取当前 BufferedEventWriter 回调，
避免层层传参；Turn 外壳在进出时 set/clear。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Awaitable, Callable

EventWriter = Callable[..., Awaitable[None]]

_event_writer: ContextVar[EventWriter | None] = ContextVar("event_writer", default=None)


def set_event_writer(writer: EventWriter | None) -> None:
    """绑定（或清空）当前协程上下文的事件写回器。

    参数:
        writer: 异步写事件回调；None 表示解绑。
    """
    _event_writer.set(writer)


def get_event_writer() -> EventWriter | None:
    """读取当前上下文绑定的事件写回器。

    返回:
        EventWriter 或 None（未绑定）。
    """
    return _event_writer.get()
