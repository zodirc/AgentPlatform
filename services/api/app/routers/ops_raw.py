"""Ops raw snapshot read API (HM2) — never model-facing."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.pool import get_pool
from app.services.ops.auth import require_ops_eval_auth

router = APIRouter(
    prefix="/ops/raw",
    tags=["ops-raw"],
    dependencies=[Depends(require_ops_eval_auth)],
)


@router.get("/turns/{turn_id}")
async def get_turn_raw_snapshots(turn_id: UUID) -> dict[str, Any]:
    pool = await get_pool()
    turn = await pool.fetchval("SELECT id FROM turns WHERE id = $1", turn_id)
    if turn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")
    rows = await pool.fetch(
        """
        SELECT step_index, tools_fingerprint, messages, created_at
        FROM session_raw_snapshots
        WHERE turn_id = $1
        ORDER BY step_index ASC, created_at ASC
        """,
        turn_id,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        msgs = row["messages"]
        if isinstance(msgs, str):
            try:
                msgs = json.loads(msgs)
            except json.JSONDecodeError:
                msgs = []
        items.append(
            {
                "step_index": row["step_index"],
                "tools_fingerprint": row["tools_fingerprint"],
                "message_count": len(msgs) if isinstance(msgs, list) else 0,
                "messages": msgs if isinstance(msgs, list) else [],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
    return {"turn_id": str(turn_id), "count": len(items), "snapshots": items}
