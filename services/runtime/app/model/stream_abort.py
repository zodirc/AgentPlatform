
"""abort 时硬关闭 Provider HTTP 流，解除 aiter_lines 阻塞。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AbortWaitable(Protocol):
    """作用：abort 等待协议。"""
    def is_set(self) -> bool: ...

    async def wait(self) -> None: ...


async def close_response_on_abort(resp: Any, abort: AbortWaitable | None) -> None:
    """作用：abort 后 aclose httpx 响应以 unblock 流。"""
    if abort is None:
        return
    try:
        await abort.wait()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("abort wait failed", exc_info=True)
        return
    try:
        await resp.aclose()
    except Exception:
        logger.debug("response aclose after abort failed", exc_info=True)
