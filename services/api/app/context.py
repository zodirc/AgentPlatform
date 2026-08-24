"""请求级上下文变量（request_id）。

通过 ``contextvars`` 在 async 调用链中传递 ``X-Request-ID``，供 runtime 客户端、
日志与错误响应关联同一请求。
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

_request_id: ContextVar[UUID | None] = ContextVar("request_id", default=None)


def get_request_id() -> UUID | None:
    """读取当前 async 上下文中的 request_id。

    参数:
        无。

    返回:
        已绑定的 UUID；未设置 middleware 时为 None。
    """
    return _request_id.get()


def set_request_id(value: UUID) -> None:
    """在当前 async 上下文中绑定 request_id。

    参数:
        value: 由 ``RequestContextMiddleware`` 解析或生成的请求 UUID。

    返回:
        无。
    """
    _request_id.set(value)
