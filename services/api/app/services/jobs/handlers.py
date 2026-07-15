from __future__ import annotations

import json
import logging
from uuid import UUID

from app.db.pool import get_pool
from app.services.command.runtime_client import RuntimeClient
from app.services.projection.session_projector import project_session
from app.services.projection.projector import project_turn

logger = logging.getLogger(__name__)


async def handle_projection_refresh(payload: dict) -> None:
    turn_id = UUID(payload["turn_id"])
    await project_turn(turn_id)


async def handle_sources_index_sync(_payload: dict) -> None:
    client = RuntimeClient()
    await client.sync_sources_index()


async def _session_turn_count(pool, session_id) -> int:
    value = await pool.fetchval(
        "SELECT COUNT(*)::int FROM turns WHERE session_id = $1",
        session_id,
    )
    return int(value or 0)


async def handle_session_summary(payload: dict) -> None:
    turn_id = UUID(payload["turn_id"])
    await project_turn(turn_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT t.session_id, tv.latest_output, tv.status, t.user_input
        FROM turns t
        JOIN turn_views tv ON tv.turn_id = t.id
        WHERE t.id = $1
        """,
        turn_id,
    )
    if row is None:
        return

    existing = await pool.fetchrow(
        "SELECT context_summary FROM sessions WHERE id = $1",
        row["session_id"],
    )
    prior_summary = existing["context_summary"] if existing else None
    if isinstance(prior_summary, str):
        try:
            prior_summary = json.loads(prior_summary)
        except json.JSONDecodeError:
            prior_summary = None
    if isinstance(prior_summary, dict):
        if prior_summary.get("source") == "manual_compact" and prior_summary.get("last_turn_id") == str(
            turn_id
        ):
            await project_session(row["session_id"])
            return

    latest_output = row["latest_output"] or ""
    user_input = row["user_input"] or ""
    files: list[str] = []
    for text in (user_input, latest_output):
        for token in text.split():
            if "." in token and "/" in token:
                files.append(token.strip(".,;:\"'`"))
    summary = {
        "last_turn_id": str(turn_id),
        "last_status": row["status"],
        "last_output_preview": latest_output[:500],
        "turn_count": await _session_turn_count(pool, row["session_id"]),
        "task": user_input[:300],
        "files_touched": files[:20],
        "decisions": [latest_output[:240]] if latest_output else [],
        "open_items": [],
        "source": "turn_complete",
    }
    await pool.execute(
        """
        UPDATE sessions
        SET context_summary = $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        row["session_id"],
        json.dumps(summary),
    )
    await project_session(row["session_id"])


async def handle_verify_sample(payload: dict) -> None:
    """Night/offline sample ≤5% of recent completed sessions (docs/17 S3 A4)."""
    import random

    sample_rate = float(payload.get("sample_rate", 0.05))
    sample_rate = min(max(sample_rate, 0.0), 0.05)
    limit = int(payload.get("limit", 40))
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id::text AS session_id
        FROM sessions
        ORDER BY updated_at DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    selected = [r["session_id"] for r in rows if random.random() < sample_rate]
    if not selected and rows:
        # Always exercise at least one when cron fires with tiny N.
        selected = [rows[0]["session_id"]]
    client = RuntimeClient()
    reports: list[dict] = []
    for session_id in selected[:5]:
        try:
            reports.append(await client.verify_pass(session_id=session_id))
        except Exception:
            logger.exception("verify sample failed session=%s", session_id)
    logger.info(
        "verify.sample done rate=%.3f selected=%s reports=%s",
        sample_rate,
        len(selected),
        len(reports),
    )


HANDLERS = {
    "projection.refresh": handle_projection_refresh,
    "sources.index_sync": handle_sources_index_sync,
    "session.summary": handle_session_summary,
    "verify.sample": handle_verify_sample,
    # A21 night batch: same offline pass as verify.sample (exports/drafts → report).
    "critique.batch": handle_verify_sample,
}


async def dispatch_job(job_type: str, payload: dict) -> None:
    handler = HANDLERS.get(job_type)
    if handler is None:
        raise ValueError(f"unknown job type: {job_type}")
    await handler(payload)
