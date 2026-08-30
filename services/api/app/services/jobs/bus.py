"""Enqueue async jobs onto Redis Streams (ADR-020 platform bus)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

STREAM_JOBS = "agent.jobs"


def enqueue_job(
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
) -> str:
    """XADD onto ``agent.jobs``. Requires ``settings.redis_url``."""
    url = (settings.redis_url or "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is required to enqueue platform jobs")
    import redis

    jid = job_id or str(uuid.uuid4())
    body = {
        "id": jid,
        "type": job_type,
        "payload": json.dumps(payload or {}, separators=(",", ":")),
        "ts": str(time.time()),
    }
    client = redis.Redis.from_url(url, decode_responses=True)
    client.xadd(STREAM_JOBS, body, maxlen=100_000, approximate=True)
    logger.info("bus enqueue type=%s id=%s", job_type, jid)
    return jid
