"""Ops retrieval audit — read-only view of front-end user Turn RAG stages (HM5)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db.pool import get_pool
from app.services.ops.auth import require_ops_eval_auth

router = APIRouter(
    prefix="/ops/retrieval",
    tags=["ops-retrieval"],
    dependencies=[Depends(require_ops_eval_auth)],
)


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


@router.get("/recent")
async def list_recent_retrieval_turns(
    limit: int = Query(40, ge=1, le=100),
) -> dict[str, Any]:
    """Browse recent user Turns that have at least one retrieval.completed event."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            t.id AS turn_id,
            t.session_id,
            t.scenario_id,
            t.status,
            LEFT(t.user_input, 160) AS user_preview,
            t.created_at,
            s.owner_user_id,
            s.work_id,
            COUNT(e.*)::int AS retrieval_count,
            MAX(e.ts) AS last_retrieval_at,
            (ARRAY_AGG(e.payload->>'query' ORDER BY e.ts DESC))[1] AS last_query,
            (ARRAY_AGG(NULLIF(e.payload->>'hit_count', '')::int ORDER BY e.ts DESC))[1]
                AS last_hit_count
        FROM turn_events e
        JOIN turns t ON t.id = e.turn_id
        JOIN sessions s ON s.id = t.session_id
        WHERE e.type = 'retrieval.completed'
        GROUP BY
            t.id, t.session_id, t.scenario_id, t.status, t.user_input, t.created_at,
            s.owner_user_id, s.work_id
        ORDER BY MAX(e.ts) DESC
        LIMIT $1
        """,
        limit,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "turn_id": str(row["turn_id"]),
                "session_id": str(row["session_id"]),
                "scenario_id": row["scenario_id"],
                "status": row["status"],
                "user_preview": row["user_preview"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
                "work_id": str(row["work_id"]) if row["work_id"] else None,
                "retrieval_count": int(row["retrieval_count"] or 0),
                "last_retrieval_at": (
                    row["last_retrieval_at"].isoformat() if row["last_retrieval_at"] else None
                ),
                "last_query": row["last_query"],
                "last_hit_count": row["last_hit_count"],
            }
        )
    return {"count": len(items), "items": items}


@router.get("/turns/{turn_id}")
async def get_turn_retrieval_audit(turn_id: UUID) -> dict[str, Any]:
    """Return every ``retrieval.completed`` event for a real user Turn (Ops only)."""
    pool = await get_pool()
    turn = await pool.fetchrow(
        """
        SELECT t.id AS turn_id, t.session_id, t.scenario_id, t.status,
               s.owner_user_id, s.work_id
        FROM turns t
        JOIN sessions s ON s.id = t.session_id
        WHERE t.id = $1
        """,
        turn_id,
    )
    if turn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Turn not found")

    rows = await pool.fetch(
        """
        SELECT sequence, step_index, type, payload, ts
        FROM turn_events
        WHERE turn_id = $1 AND type = 'retrieval.completed'
        ORDER BY sequence ASC
        """,
        turn_id,
    )
    retrievals: list[dict[str, Any]] = []
    for row in rows:
        payload = _parse_payload(row["payload"])
        audit = payload.get("audit") if isinstance(payload.get("audit"), dict) else None
        retrievals.append(
            {
                "sequence": int(row["sequence"]),
                "step_index": row["step_index"],
                "ts": row["ts"].isoformat() if row["ts"] is not None else None,
                "query": payload.get("query"),
                "mode": payload.get("mode"),
                "hit_count": payload.get("hit_count"),
                "summary": payload.get("summary"),
                "hits": payload.get("hits") if isinstance(payload.get("hits"), list) else [],
                "index": payload.get("index") if isinstance(payload.get("index"), dict) else None,
                "filters": payload.get("filters")
                if isinstance(payload.get("filters"), dict)
                else None,
                "audit": audit,
            }
        )

    return {
        "turn_id": str(turn["turn_id"]),
        "session_id": str(turn["session_id"]),
        "scenario_id": turn["scenario_id"],
        "status": turn["status"],
        "owner_user_id": str(turn["owner_user_id"]) if turn["owner_user_id"] else None,
        "work_id": str(turn["work_id"]) if turn["work_id"] else None,
        "retrieval_count": len(retrievals),
        "retrievals": retrievals,
    }
