from __future__ import annotations

import logging

from app.db.pool import get_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


async def check_monthly_token_alert() -> None:
    limit = settings.monthly_token_limit
    if limit <= 0:
        return

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT COALESCE(SUM(
            COALESCE((payload->'token_usage'->>'input_tokens')::bigint, 0) +
            COALESCE((payload->'token_usage'->>'output_tokens')::bigint, 0)
        ), 0) AS total
        FROM turn_events
        WHERE type = 'turn.completed'
          AND ts >= date_trunc('month', timezone('utc', now()))
        """
    )
    used = int(row["total"] if row else 0)
    metrics.set_gauge("monthly_tokens_used", float(used))

    threshold = int(limit * settings.monthly_token_alert_pct)
    if used >= limit:
        metrics.inc("monthly_token_limit_alert_total", level="exceeded")
        logger.warning(
            "monthly token limit exceeded: used=%s limit=%s",
            used,
            limit,
        )
    elif used >= threshold:
        metrics.inc("monthly_token_limit_alert_total", level="warning")
        logger.warning(
            "monthly token alert threshold reached: used=%s threshold=%s limit=%s",
            used,
            threshold,
            limit,
        )
