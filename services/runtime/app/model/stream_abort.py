"""Helpers to hard-close provider HTTP streams when abort fires.

Happy path: the watcher only awaits ``abort.wait()`` — no polling, no extra
work until CancelTurn sets the gateway cancel event.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class AbortWaitable(Protocol):
    def is_set(self) -> bool: ...

    async def wait(self) -> None: ...


async def close_response_on_abort(resp: Any, abort: AbortWaitable | None) -> None:
    """Wait for abort, then ``aclose`` the httpx response to unblock ``aiter_lines``."""
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
