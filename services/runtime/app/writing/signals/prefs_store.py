"""账户 prefs 加载缓存。"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

from app.writing.signals.prefs_loader import _module as _writing_prefs

merge_prefs = _writing_prefs().merge_prefs
platform_prefs_payload = _writing_prefs().platform_prefs_payload

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_S = 60.0


async def load_account_prefs(owner_user_id: UUID | None) -> dict[str, Any]:
    """加载 merge prefs。
    
    参数:
        owner_user_id。
    
    返回:
        dict。"""
    if owner_user_id is None:
        return platform_prefs_payload()
    key = str(owner_user_id)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    from app.ports import prefs_source

    stored = await prefs_source().load_account(owner_user_id)
    if stored is None:
        merged = platform_prefs_payload()
    else:
        updated_at = stored.get("updated_at")
        merged = merge_prefs(stored)
        merged["updated_at"] = updated_at
    _CACHE[key] = (now + _CACHE_TTL_S, merged)
    return merged


def invalidate_prefs_cache(owner_user_id: UUID | str | None) -> None:
    """失效缓存。
    
    参数:
        owner_user_id。
    
    返回:
        None。"""
    if owner_user_id is None:
        _CACHE.clear()
        return
    _CACHE.pop(str(owner_user_id), None)
