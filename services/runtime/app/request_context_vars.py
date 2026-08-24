"""HTTP 请求级 ContextVar：在 middleware 与业务代码间传递 ``request_id``。"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

_request_id: ContextVar[UUID | None] = ContextVar("request_id", default=None)


def get_request_id() -> UUID | None:
    """作用：读取当前异步上下文中绑定的请求 ID。

    返回：
        已绑定的 UUID；middleware 未执行时为 ``None``。
    """
    return _request_id.get()


def set_request_id(value: UUID) -> None:
    """作用：将请求 ID 写入 ContextVar，供日志与下游关联。

    参数：
        value: 来自 ``X-Request-ID`` 头或新生成的 UUID。
    """
    _request_id.set(value)
