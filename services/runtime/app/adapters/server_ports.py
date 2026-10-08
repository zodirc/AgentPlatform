"""Postgres 上的写作端口。仅服务器进程导入。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.db.pool import get_pool


class PostgresEvaluationStore:
    async def persist_fragment(self, **kwargs: Any) -> str | None:
        return await _persist_fragment(**kwargs)

    async def load_turn(self, turn_id: UUID) -> list[dict[str, Any]]:
        return await _load_turn_evaluations(turn_id)


class PostgresPrefsSource:
    async def load_account(self, owner_user_id: UUID) -> dict[str, Any] | None:
        pool = await get_pool()
        row = await pool.fetchrow(
            """
            SELECT preset_label, fragment_weights, signal_penalties, signal_rewards,
                   schema_version, updated_at
            FROM writing_account_prefs
            WHERE owner_user_id = $1
            """,
            owner_user_id,
        )
        if row is None:
            return None
        return {
            "preset_label": row["preset_label"],
            "fragment_weights": row["fragment_weights"],
            "signal_penalties": row["signal_penalties"],
            "signal_rewards": row["signal_rewards"],
            "schema_version": row["schema_version"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


async def load_context_summary(session_id: UUID):
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT context_summary FROM sessions WHERE id = $1",
        session_id,
    )


async def save_context_summary(session_id: UUID, record: dict[str, Any]) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE sessions
        SET context_summary = $2::jsonb, updated_at = now()
        WHERE id = $1
        """,
        session_id,
        json.dumps(record, ensure_ascii=False),
    )


async def _persist_fragment(**kwargs: Any) -> str | None:
    text = kwargs["text"]
    writing_signals = kwargs["writing_signals"]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = json.dumps(writing_signals, ensure_ascii=False)
    sig_payload = kwargs.get("signature")
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
            kwargs["owner_user_id"],
            kwargs.get("work_id"),
            kwargs.get("session_id"),
            kwargs.get("turn_id"),
            kwargs.get("section_id") or None,
            kwargs["fragment_declared"],
            kwargs["fragment_detected"],
            payload,
            digest,
            kwargs.get("feature_schema_id") or None,
            json.dumps(sig_payload, ensure_ascii=False) if sig_payload else None,
            kwargs.get("prototype_scope") or None,
            kwargs.get("nearest_exemplar_slug"),
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
            kwargs["owner_user_id"],
            kwargs.get("work_id"),
            kwargs.get("session_id"),
            kwargs.get("turn_id"),
            kwargs.get("section_id") or None,
            kwargs["fragment_declared"],
            kwargs["fragment_detected"],
            payload,
            digest,
        )
    if row is None:
        return None
    return str(row["id"])


async def _load_turn_evaluations(turn_id: UUID) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, section_id, fragment_declared, writing_signals, created_at
        FROM writing_fragment_evaluations
        WHERE turn_id = $1
        ORDER BY created_at ASC
        """,
        turn_id,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        signals = row["writing_signals"]
        if isinstance(signals, str):
            try:
                signals = json.loads(signals)
            except json.JSONDecodeError:
                signals = {}
        out.append(
            {
                "id": row["id"],
                "section_id": row["section_id"],
                "fragment_declared": row["fragment_declared"],
                "writing_signals": signals if isinstance(signals, dict) else {},
                "created_at": str(row["created_at"] or ""),
            }
        )
    return out
