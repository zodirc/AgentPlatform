"""Redis Pub/Sub for Turn wake and live fanout (not claim ownership).

English: Fire-and-forget channels. Lost messages are recovered by PG poll /
durable ``turn_events`` SELECT. Never XACK a Turn here.

Channels
--------
- ``turn.dispatch`` — payload = run_id UUID text (doorbell after accepted Run)
- ``turn.live.<turn_id>`` — live delta envelopes (may omit PG sequence)

``agent.jobs`` Streams remain for async index work only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.settings import settings

logger = logging.getLogger(__name__)

CHANNEL_TURN_DISPATCH = "turn.dispatch"
CHANNEL_TURN_LIVE_PREFIX = "turn.live."
CHANNEL_TURN_LIVE_PATTERN = "turn.live.*"


def _redis_url() -> str:
    return (getattr(settings, "redis_url", None) or "").strip()


def _sync_redis():
    url = _redis_url()
    if not url:
        raise RuntimeError("REDIS_URL empty")
    import redis

    return redis.Redis.from_url(url, decode_responses=True)


def publish_turn_dispatch(run_id: UUID | str) -> bool:
    """PUBLISH turn.dispatch after PG COMMIT. Returns False if Redis unavailable."""
    if not _redis_url():
        logger.warning("turn.dispatch skip: REDIS_URL empty")
        return False
    try:
        client = _sync_redis()
        n = int(client.publish(CHANNEL_TURN_DISPATCH, str(run_id)))
        logger.debug("turn.dispatch published run_id=%s receivers=%s", run_id, n)
        return True
    except Exception:
        logger.exception("turn.dispatch publish failed run_id=%s", run_id)
        return False


def publish_turn_live(turn_id: UUID | str, envelope: dict[str, Any]) -> bool:
    """PUBLISH one live event envelope to turn.live.<turn_id>."""
    if not _redis_url():
        return False
    try:
        channel = f"{CHANNEL_TURN_LIVE_PREFIX}{turn_id}"
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
        client = _sync_redis()
        client.publish(channel, body)
        return True
    except Exception:
        logger.exception("turn.live publish failed turn_id=%s", turn_id)
        return False


async def listen_turn_dispatch(
    on_run_id: Callable[[UUID | None], Awaitable[None]],
    *,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Subscribe turn.dispatch until cancelled / should_stop.

    Payload parse failures wake with ``None`` (caller may poll queue head).
    """
    url = _redis_url()
    if not url:
        raise RuntimeError("REDIS_URL required for turn.dispatch subscribe")

    import asyncio

    import redis.asyncio as aioredis

    client = aioredis.from_url(url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL_TURN_DISPATCH)
    logger.info("turn.dispatch Redis subscribe started")
    try:
        while True:
            if should_stop and should_stop():
                break
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.01)
                continue
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            run_id: UUID | None
            try:
                run_id = UUID(str(raw))
            except (ValueError, TypeError):
                run_id = None
            await on_run_id(run_id)
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL_TURN_DISPATCH)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await client.aclose()
        except Exception:
            pass
