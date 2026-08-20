from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

from app.writing.signals.prefs_loader import _module as _writing_prefs

merge_prefs = _writing_prefs().merge_prefs
platform_prefs_payload = _writing_prefs().platform_prefs_payload

from app.db.pool import get_pool

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_S = 60.0


async def load_account_prefs(owner_user_id: UUID | None) -> dict[str, Any]:
    if owner_user_id is None:
        return platform_prefs_payload()
    key = str(owner_user_id)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

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
        merged = platform_prefs_payload()
    else:
        stored = {
            "preset_label": row["preset_label"],
            "fragment_weights": row["fragment_weights"],
            "signal_penalties": row["signal_penalties"],
            "signal_rewards": row["signal_rewards"],
            "schema_version": row["schema_version"],
        }
        merged = merge_prefs(stored)
        merged["updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
    _CACHE[key] = (now + _CACHE_TTL_S, merged)
    return merged


def invalidate_prefs_cache(owner_user_id: UUID | str | None) -> None:
    if owner_user_id is None:
        _CACHE.clear()
        return
    _CACHE.pop(str(owner_user_id), None)
