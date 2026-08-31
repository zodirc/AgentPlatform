"""Redis Pub/Sub for Turn dispatch wake and live SSE fanout (api side).

Mirrors runtime ``platform_bus.pubsub``. Claim ownership stays in Postgres.
"""

from __future__ import annotations

import asyncio
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
    """PUBLISH after create_turn COMMIT. Failures are logged only."""
    if not _redis_url():
        logger.warning("turn.dispatch skip: REDIS_URL empty")
        return False
    try:
        client = _sync_redis()
        client.publish(CHANNEL_TURN_DISPATCH, str(run_id))
        return True
    except Exception:
        logger.exception("turn.dispatch publish failed run_id=%s", run_id)
        return False


def wake_mode() -> str:
    """postgres | redis | both (default redis)."""
    raw = (getattr(settings, "turn_dispatch_wake", None) or "redis").strip().lower()
    if raw in {"postgres", "pg", "notify"}:
        return "postgres"
    if raw in {"both", "all"}:
        return "both"
    return "redis"


def should_pg_notify_dispatch() -> bool:
    return wake_mode() in {"postgres", "both"}


def should_redis_publish_dispatch() -> bool:
    return wake_mode() in {"redis", "both"}


async def listen_turn_live(
    on_envelope: Callable[[UUID, dict[str, Any]], Awaitable[None]],
    *,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """PSUBSCRIBE turn.live.* and forward JSON envelopes."""
    url = _redis_url()
    if not url:
        raise RuntimeError("REDIS_URL required for turn.live subscribe")

    import redis.asyncio as aioredis

    client = aioredis.from_url(url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.psubscribe(CHANNEL_TURN_LIVE_PATTERN)
    logger.info("turn.live Redis psubscribe started")
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
            if message.get("type") != "pmessage":
                continue
            channel = str(message.get("channel") or "")
            if not channel.startswith(CHANNEL_TURN_LIVE_PREFIX):
                continue
            turn_raw = channel[len(CHANNEL_TURN_LIVE_PREFIX) :]
            try:
                turn_id = UUID(turn_raw)
            except ValueError:
                continue
            raw = message.get("data")
            try:
                envelope = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, json.JSONDecodeError):
                logger.warning("turn.live bad json turn_id=%s", turn_id)
                continue
            if not isinstance(envelope, dict):
                continue
            await on_envelope(turn_id, envelope)
    finally:
        try:
            await pubsub.punsubscribe(CHANNEL_TURN_LIVE_PATTERN)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await client.aclose()
        except Exception:
            pass
