"""Audit trail for sensitive operations (B17).

Best-effort by design: an audit insert failure must never fail the user's
action, so errors are logged and swallowed.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.db.pool import get_pool
from app.services.end_user.users import EndUser

logger = logging.getLogger(__name__)


async def record_audit(
    *,
    actor: EndUser | None,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO audit_log (actor_user_id, actor_username, action,
                                   resource_type, resource_id, detail)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            actor.id if actor is not None else None,
            actor.username if actor is not None else None,
            action,
            resource_type,
            str(resource_id) if resource_id is not None else None,
            json.dumps(detail) if detail else None,
        )
    except Exception:
        logger.exception("audit write failed action=%s resource=%s", action, resource_id)
