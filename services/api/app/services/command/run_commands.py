"""Enqueue run control commands via DB + NOTIFY (O2 / WP6)."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from app.db.pool import get_pool

logger = logging.getLogger(__name__)

COMMAND_TYPES = frozenset(
    {"approve", "deny", "patch_accept", "patch_reject", "cancel"}
)


async def enqueue_run_command(
    *,
    run_id: UUID,
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> UUID:
    """Insert pending command + notify owner runtime. Returns command id.

    If an identical pending row already exists (unique index), returns that id.
    """
    if command_type not in COMMAND_TYPES:
        raise ValueError(f"unknown run command type: {command_type}")
    cmd_id = uuid4()
    body = payload or {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO run_commands (id, run_id, type, payload, status)
                VALUES ($1, $2, $3, $4::jsonb, 'pending')
                ON CONFLICT (run_id, type) WHERE status = 'pending'
                DO UPDATE SET payload = EXCLUDED.payload
                RETURNING id
                """,
                cmd_id,
                run_id,
                command_type,
                json.dumps(body),
            )
            await conn.execute(
                "SELECT pg_notify('run_commands_channel', $1)",
                str(run_id),
            )
    return row["id"] if row else cmd_id
