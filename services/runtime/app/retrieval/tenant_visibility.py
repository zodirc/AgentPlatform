"""多租户可见性与索引 path 编解码（RAG ACL 防御层）。

职责：hit 是否对当前 Work/seed 可见；private 行 storage path 加 ``__work__/`` 前缀。
在 RAG 链路中的位置：pgvector 查询 SQL 过滤 + 返回 path 展示 + inspect 工具。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID


def _is_seed_path(rel_path: str) -> bool:
    normalized = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def path_visible_in_current_work(rel_path: str) -> bool:
    """路径为 seed 或在当前 work_root 沙箱内时为 True。"""
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
    """路径沙箱 + work_id/visibility 元数据双重校验（含 orphan private 拦截）。"""
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
    """丢弃当前 Work 不可见的 hit（seed 例外由 context 控制）。"""
    return [hit for hit in hits if hit_visible_for_tenant(hit)]


def index_storage_path(rel_path: str, *, work_id: str | None, visibility: str) -> str:
    """private 行加 work 作用域前缀，避免跨 Work path PK 冲突（MT5c）。"""
    normalized = (rel_path or "").strip().lstrip("/").replace("\\", "/")
    vis = (visibility or "private").strip() or "private"
    if vis == "seed" or not work_id:
        return normalized
    return f"__work__/{work_id}/{normalized}"


def display_path_from_index(index_path: str) -> str:
    """索引 storage path → 工具/citation 展示用相对路径。"""
    normalized = (index_path or "").strip().lstrip("/").replace("\\", "/")
    if normalized.startswith("__work__/"):
        parts = normalized.split("/", 2)
        if len(parts) == 3:
            return parts[2]
    return normalized
