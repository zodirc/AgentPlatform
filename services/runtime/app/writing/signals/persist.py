from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.db.pool import get_pool


async def persist_fragment_evaluation(
    *,
    owner_user_id: UUID,
    work_id: UUID | None,
    session_id: UUID | None,
    turn_id: UUID | None,
    section_id: str,
    fragment_declared: str,
    fragment_detected: str,
    writing_signals: dict[str, Any],
    text: str,
    feature_schema_id: str = "",
    signature: dict[str, Any] | None = None,
    prototype_scope: str = "",
    nearest_exemplar_slug: str | None = None,
) -> str | None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = json.dumps(writing_signals, ensure_ascii=False)
    sig_payload = signature
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO writing_fragment_evaluations (
                owner_user_id, work_id, session_id, turn_id, section_id,
                fragment_declared, fragment_detected, writing_signals, text_sha256,
                feature_schema_id, signature, prototype_scope, nearest_exemplar_slug
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11::jsonb, $12, $13)
            RETURNING id
            """,
            owner_user_id,
            work_id,
            session_id,
            turn_id,
            section_id or None,
            fragment_declared,
            fragment_detected,
            payload,
            digest,
            feature_schema_id or None,
            json.dumps(sig_payload, ensure_ascii=False) if sig_payload else None,
            prototype_scope or None,
            nearest_exemplar_slug,
        )
    except Exception:
        row = await pool.fetchrow(
            """
            INSERT INTO writing_fragment_evaluations (
                owner_user_id, work_id, session_id, turn_id, section_id,
                fragment_declared, fragment_detected, writing_signals, text_sha256
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
            RETURNING id
            """,
            owner_user_id,
            work_id,
            session_id,
            turn_id,
            section_id or None,
            fragment_declared,
            fragment_detected,
            payload,
            digest,
        )
    if row is None:
        return None
    return str(row["id"])
