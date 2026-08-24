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
    """写入 ``audit_log`` 表（best-effort，失败不阻断用户操作）。

    参数:
        actor: 操作者；None 表示匿名/系统。
        action: 动作标识（如 ``login``、``delete_session``）。
        resource_type: 资源类型名。
        resource_id: 可选资源 id。
        detail: 可选 JSON 细节。

    返回:
        无。

    异常:
        无；插入失败仅 ``logger.exception``。
    """
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
