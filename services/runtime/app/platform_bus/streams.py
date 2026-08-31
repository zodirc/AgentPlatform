"""Redis Streams job bus for async execution-plane work.

English: XADD / XREADGROUP helpers. Sync hot paths (first token, query embed)
must not use this module — only Turn-external or long jobs.

Turn wake / live fanout use ``platform_bus.pubsub`` (Pub/Sub), not this stream.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

STREAM_JOBS = "agent.jobs"
GROUP_RETRIEVAL = "sources-retrieval"
GROUP_SANDBOX = "sandbox"
GROUP_ORCHESTRATOR = "runtime"


def _redis():
    url = (getattr(settings, "redis_url", None) or "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is required for the platform job bus")
    import redis

    return redis.Redis.from_url(url, decode_responses=True)


def enqueue_job(
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
) -> str:
    """Append a job to ``agent.jobs``. Returns job id."""
    jid = job_id or str(uuid.uuid4())
    body = {
        "id": jid,
        "type": job_type,
        "payload": json.dumps(payload or {}, separators=(",", ":")),
        "ts": str(time.time()),
    }
    client = _redis()
    client.xadd(STREAM_JOBS, body, maxlen=100_000, approximate=True)
    logger.info("bus enqueue type=%s id=%s", job_type, jid)
    return jid


def ensure_consumer_group(group: str) -> None:
    """Create consumer group on ``agent.jobs`` if missing."""
    client = _redis()
    try:
        client.xgroup_create(STREAM_JOBS, group, id="0", mkstream=True)
    except Exception as exc:
        # BUSYGROUP = already exists
        if "BUSYGROUP" not in str(exc).upper():
            raise


def read_jobs(
    group: str,
    consumer: str,
    *,
    count: int = 8,
    block_ms: int = 2000,
) -> list[tuple[str, dict[str, str]]]:
    """Blocking read for ``group``. Returns ``[(stream_id, fields), ...]``."""
    client = _redis()
    raw = client.xreadgroup(
        group,
        consumer,
        streams={STREAM_JOBS: ">"},
        count=max(1, count),
        block=max(1, block_ms),
    )
    out: list[tuple[str, dict[str, str]]] = []
    if not raw:
        return out
    for _stream, messages in raw:
        for msg_id, fields in messages:
            out.append((str(msg_id), {str(k): str(v) for k, v in fields.items()}))
    return out


def ack_job(group: str, message_id: str) -> None:
    """Acknowledge a processed stream message."""
    _redis().xack(STREAM_JOBS, group, message_id)


def parse_payload(fields: dict[str, str]) -> dict[str, Any]:
    """Decode JSON payload from stream fields."""
    raw = fields.get("payload") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
