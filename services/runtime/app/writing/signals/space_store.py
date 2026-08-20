"""Optional Postgres overlay for account/work exemplars (index plane)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.writing.signals.bank import Exemplar
from app.writing.signals.signature import FEATURE_SCHEMA_ID
from app.writing.signals.space import MetricSpace, exemplars_from_rows, overlay_space


async def load_overlay_exemplars(
    *,
    owner_user_id: UUID | None,
    work_id: UUID | None,
) -> tuple[str, dict[str, tuple[Exemplar, ...]]]:
    """Return (scope, bank) for the highest overlay that has rows; else empty."""
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
    from app.writing.signals.space import load_platform_space

    base = load_platform_space()
    scope, extra = await load_overlay_exemplars(
        owner_user_id=owner_user_id,
        work_id=work_id,
    )
    if not extra:
        return base
    return overlay_space(base, extra, scope=scope)
