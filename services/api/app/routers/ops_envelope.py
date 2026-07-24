"""Ops model envelope read API (HM4)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db.pool import get_pool
from app.services.ops.auth import require_ops_eval_auth

router = APIRouter(
    prefix="/ops/envelopes",
    tags=["ops-envelopes"],
    dependencies=[Depends(require_ops_eval_auth)],
)


@router.get("/recent")
async def list_recent_envelope_turns(
    limit: int = Query(40, ge=1, le=100),
) -> dict[str, Any]:
    """Browse recent Turns that have at least one sampled model request envelope."""
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT
                e.turn_id,
                t.session_id,
                t.scenario_id,
                t.status,
                LEFT(t.user_input, 160) AS user_preview,
                s.owner_user_id,
                COUNT(*)::int AS envelope_count,
                COUNT(*) FILTER (WHERE e.envelope IS NOT NULL)::int AS full_count,
                MAX(e.created_at) AS last_at,
                MAX(e.fill_ratio) AS max_fill_ratio
            FROM model_request_envelopes e
            JOIN turns t ON t.id = e.turn_id
            JOIN sessions s ON s.id = t.session_id
            GROUP BY
                e.turn_id, t.session_id, t.scenario_id, t.status, t.user_input,
                s.owner_user_id
            ORDER BY MAX(e.created_at) DESC
            LIMIT $1
            """,
            limit,
        )
    except Exception:
        # Table may not exist until migration; Ops page should still open.
        return {"count": 0, "items": [], "error": "model_request_envelopes unavailable"}

    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "turn_id": str(row["turn_id"]),
                "session_id": str(row["session_id"]),
                "scenario_id": row["scenario_id"],
                "status": row["status"],
                "user_preview": row["user_preview"],
                "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
                "envelope_count": int(row["envelope_count"] or 0),
                "full_count": int(row["full_count"] or 0),
                "last_at": row["last_at"].isoformat() if row["last_at"] else None,
                "max_fill_ratio": float(row["max_fill_ratio"])
                if row["max_fill_ratio"] is not None
                else None,
            }
        )
    return {"count": len(items), "items": items}


@router.get("/turns/{turn_id}")
async def get_turn_envelopes(turn_id: UUID) -> dict[str, Any]:
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT step_index, content_hash, fill_ratio, envelope, created_at
            FROM model_request_envelopes
            WHERE turn_id = $1
            ORDER BY step_index ASC, created_at ASC
            """,
            turn_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model_request_envelopes unavailable (run migrations)",
        ) from exc
    if not rows:
        turn = await pool.fetchval("SELECT id FROM turns WHERE id = $1", turn_id)
        if turn is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")
    items: list[dict[str, Any]] = []
    for row in rows:
        env = row["envelope"]
        if isinstance(env, str):
            try:
                env = json.loads(env)
            except json.JSONDecodeError:
                env = None
        items.append(
            {
                "step_index": row["step_index"],
                "content_hash": row["content_hash"],
                "fill_ratio": row["fill_ratio"],
                "has_full_envelope": env is not None,
                "envelope": env,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
    return {"turn_id": str(turn_id), "count": len(items), "envelopes": items}
