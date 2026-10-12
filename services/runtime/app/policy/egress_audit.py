"""首次见到的出网主机记一条审计。同一进程内每个主机只记一次。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_seen: set[str] = set()


def note_egress_host(host: str, decision: str) -> None:
    name = (host or "").strip().lower()
    if not name or name in _seen:
        return
    _seen.add(name)
    logger.info("egress host %s decision=%s", name, decision)
    try:
        from app.observability.metrics import metrics

        metrics.inc("egress_host_first", decision=decision)
    except Exception:
        return
