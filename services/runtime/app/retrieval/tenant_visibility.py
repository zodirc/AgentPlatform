"""Tenant visibility for retrieval hits (docs/27 MT3 · MT5c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID


def _is_seed_path(rel_path: str) -> bool:
    normalized = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def path_visible_in_current_work(rel_path: str) -> bool:
    """True if path is seed corpus or resolves inside the bound work_root."""
    normalized = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    if not normalized:
        return False
    if _is_seed_path(normalized):
        from app.tenant_context import current_visibility_seed

        return current_visibility_seed()
    from app.tenant_context import current_work_root_path

    root = current_work_root_path()
    try:
        target = (root / normalized).resolve()
        target.relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _hit_work_id(hit: Any) -> UUID | None:
    raw: Any
    if isinstance(hit, dict):
        raw = hit.get("work_id")
    else:
        raw = getattr(hit, "work_id", None)
    if raw is None or raw == "":
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def hit_visible_for_tenant(hit: Any) -> bool:
    """Defense in depth: path sandbox + optional work_id metadata match."""
    if isinstance(hit, dict):
        path = str(hit.get("path") or "")
        visibility = str(hit.get("visibility") or "")
    else:
        path = str(getattr(hit, "path", "") or "")
        visibility = str(getattr(hit, "visibility", "") or "")

    if visibility == "seed" or _is_seed_path(path):
        from app.tenant_context import current_visibility_seed

        return current_visibility_seed()

    wid = _hit_work_id(hit)
    if visibility == "private" and wid is None and not _is_seed_path(path):
        # Orphan private rows must not leak via post-filter either (MT5c).
        return False
    if wid is not None:
        from app.tenant_context import current_work_id

        current = current_work_id()
        if current is None or wid != current:
            return False

    return path_visible_in_current_work(path)


def filter_hits_for_tenant(hits: list[Any]) -> list[Any]:
    """Drop hits outside current Work (except seed). Supports ChunkHit or dict."""
    return [hit for hit in hits if hit_visible_for_tenant(hit)]


def index_storage_path(rel_path: str, *, work_id: str | None, visibility: str) -> str:
    """Scope private rows so path PK does not collide across Works (MT5c)."""
    normalized = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    vis = (visibility or "private").strip() or "private"
    if vis == "seed" or not work_id:
        return normalized
    return f"__work__/{work_id}/{normalized}"


def display_path_from_index(index_path: str) -> str:
    """Strip work-scope prefix for tool hits / citations."""
    normalized = (index_path or "").strip().lstrip("/").replace("\\", "/")
    if normalized.startswith("__work__/"):
        parts = normalized.split("/", 2)
        if len(parts) == 3:
            return parts[2]
    return normalized
