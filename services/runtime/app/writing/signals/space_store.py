"""Postgres exemplar overlay。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.writing.signals.bank import Exemplar
from app.writing.signals.signature import FEATURE_SCHEMA_ID, SIGNATURE_KEYS, signature_vec
from app.writing.signals.space import MetricSpace, exemplars_from_rows, overlay_space

_OVERLAY_CAP = 4


async def load_overlay_exemplars(
    *,
    owner_user_id: UUID | None,
    work_id: UUID | None,
) -> tuple[str, dict[str, tuple[Exemplar, ...]]]:
    """加载最高 overlay bank。
    
    参数:
        owner_user_id/work_id。
    
    返回:
        (scope,bank)。"""
    if owner_user_id is None and work_id is None:
        return "platform", {}
    try:
        from app.db.pool import get_pool

        pool = await get_pool()
    except Exception:
        return "platform", {}

    async def _fetch(scope: str, **params: Any) -> list:
        if scope == "work":
            return await pool.fetch(
                """
                SELECT fragment, slug, author, work_title, beat, license,
                       signature, weight, scope
                FROM writing_exemplars
                WHERE enabled AND feature_schema_id = $1
                  AND scope = 'work' AND work_id = $2
                ORDER BY updated_at DESC
                """,
                FEATURE_SCHEMA_ID,
                params["work_id"],
            )
        return await pool.fetch(
            """
            SELECT fragment, slug, author, work_title, beat, license,
                   signature, weight, scope
            FROM writing_exemplars
            WHERE enabled AND feature_schema_id = $1
              AND scope = 'account' AND owner_user_id = $2
            """,
            FEATURE_SCHEMA_ID,
            params["owner_user_id"],
        )

    try:
        if work_id is not None:
            rows = await _fetch("work", work_id=work_id)
            bank = exemplars_from_rows(dict(r) for r in rows)
            if bank:
                return "work", bank
        if owner_user_id is not None:
            rows = await _fetch("account", owner_user_id=owner_user_id)
            bank = exemplars_from_rows(dict(r) for r in rows)
            if bank:
                return "account", bank
    except Exception:
        return "platform", {}
    return "platform", {}


async def load_metric_space(
    *,
    owner_user_id: UUID | None = None,
    work_id: UUID | None = None,
) -> MetricSpace:
    """platform+overlay 空间。
    
    参数:
        owner_user_id/work_id。
    
    返回:
        MetricSpace。"""
    from app.writing.signals.space import load_platform_space

    base = load_platform_space()
    scope, extra = await load_overlay_exemplars(
        owner_user_id=owner_user_id,
        work_id=work_id,
    )
    if not extra:
        return base
    return overlay_space(base, extra, scope=scope)


async def upsert_work_overlay_beat(
    *,
    owner_user_id: UUID,
    work_id: UUID,
    fragment: str,
    section_id: str,
    text: str,
    weight: float,
    promoted_from_eval_id: Any = None,
) -> None:
    """把修好的拍写入 work overlay（签名；正文在 sidecar）。"""
    from app.db.pool import get_pool

    body = (text or "").strip()
    if not body:
        return
    vec = signature_vec(body)
    sig_map = {k: float(v) for k, v in zip(SIGNATURE_KEYS, vec)}
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    slug = f"local:{section_id or 'ch'}"
    beat = section_id or "local"
    eval_id = promoted_from_eval_id if promoted_from_eval_id else None
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO writing_exemplars (
            scope, owner_user_id, work_id, fragment, slug, author, work_title,
            beat, license, text_sha256, feature_schema_id, signature, weight,
            enabled, promoted_from_eval_id, updated_at
        ) VALUES (
            'work', $1, $2, $3, $4, '', '',
            $5, 'user_promoted', $6, $7, $8::jsonb, $9,
            TRUE, $10, now()
        )
        ON CONFLICT (work_id, fragment, slug, feature_schema_id) WHERE scope = 'work'
        DO UPDATE SET
            text_sha256 = EXCLUDED.text_sha256,
            signature = EXCLUDED.signature,
            weight = EXCLUDED.weight,
            enabled = TRUE,
            beat = EXCLUDED.beat,
            promoted_from_eval_id = EXCLUDED.promoted_from_eval_id,
            updated_at = now()
        """,
        owner_user_id,
        work_id,
        fragment,
        slug,
        beat,
        digest,
        FEATURE_SCHEMA_ID,
        json.dumps(sig_map, ensure_ascii=False),
        float(weight),
        eval_id,
    )
    await pool.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY fragment ORDER BY updated_at DESC
                   ) AS rn
            FROM writing_exemplars
            WHERE scope = 'work' AND work_id = $1 AND enabled
        )
        UPDATE writing_exemplars e
        SET enabled = FALSE
        FROM ranked
        WHERE e.id = ranked.id AND ranked.rn > $2
        """,
        work_id,
        _OVERLAY_CAP,
    )
