"""Ops raw snapshot read API (HM2) — never model-facing.

Read-only observation behind OPS_TEST_SECRET. Does not sit on the workbench
hot path; never feeds model context.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db.pool import get_pool
from app.services.ops.auth import require_ops_eval_auth
from app.services.ops.list_query import append_turn_filters, normalize_page, where_sql

router = APIRouter(
    prefix="/ops/raw",
    tags=["ops-raw"],
    dependencies=[Depends(require_ops_eval_auth)],
)


@router.get("/recent")
async def list_recent_raw_turns(
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    scenario: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    """Browse recent Turns that have at least one session_raw_snapshots row."""
    limit, offset = normalize_page(limit=limit, offset=offset)
    clauses: list[str] = []
    args: list[Any] = []
    append_turn_filters(clauses, args, status=status_filter, scenario=scenario, q=q)
    where = where_sql(clauses)
    group_by = """
        GROUP BY
            r.turn_id, t.session_id, t.scenario_id, t.status, t.user_input,
            s.owner_user_id
    """
    pool = await get_pool()
    try:
        total = int(
            await pool.fetchval(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT r.turn_id
                    FROM session_raw_snapshots r
                    JOIN turns t ON t.id = r.turn_id
                    JOIN sessions s ON s.id = t.session_id
                    {where}
                    {group_by}
                ) sub
                """,
                *args,
            )
            or 0
        )
        args.extend([limit, offset])
        lim_i, off_i = len(args) - 1, len(args)
        rows = await pool.fetch(
            f"""
            SELECT
                r.turn_id,
                t.session_id,
                t.scenario_id,
                t.status,
                LEFT(t.user_input, 160) AS user_preview,
                s.owner_user_id,
                COUNT(*)::int AS snapshot_count,
                MAX(r.created_at) AS last_at,
                MAX(r.step_index)::int AS max_step_index
            FROM session_raw_snapshots r
            JOIN turns t ON t.id = r.turn_id
            JOIN sessions s ON s.id = t.session_id
            {where}
            {group_by}
            ORDER BY MAX(r.created_at) DESC
            LIMIT ${lim_i} OFFSET ${off_i}
            """,
            *args,
        )
    except Exception:
        return {
            "count": 0,
            "total": 0,
            "limit": limit,
            "offset": offset,
            "items": [],
            "error": "session_raw_snapshots unavailable",
        }

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
                "snapshot_count": int(row["snapshot_count"] or 0),
                "max_step_index": int(row["max_step_index"])
                if row["max_step_index"] is not None
                else None,
                "last_at": row["last_at"].isoformat() if row["last_at"] else None,
            }
        )
    return {"count": len(items), "total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/turns/{turn_id}")
async def get_turn_raw_snapshots(turn_id: UUID) -> dict[str, Any]:
    pool = await get_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT step_index, tools_fingerprint, messages, created_at
            FROM session_raw_snapshots
            WHERE turn_id = $1
            ORDER BY step_index ASC, created_at ASC
            """,
            turn_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session_raw_snapshots unavailable (run migrations)",
        ) from exc
    if not rows:
        turn = await pool.fetchval("SELECT id FROM turns WHERE id = $1", turn_id)
        if turn is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")
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
