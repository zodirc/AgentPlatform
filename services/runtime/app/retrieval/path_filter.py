"""``search_sources`` 的 path_prefix 规范化与命中过滤（RAG 查询约束）。

在 RAG 链路中的位置：工具层解析模型传入 prefix，检索后按 prefix 过滤 hits。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


SOURCES_ROOT = "sources"


def normalize_path_prefix(path_prefix: str | None) -> tuple[str | None, str | None]:
    """规范化 path_prefix；返回 ``(normalized, error_hint)``。

    规则：相对路径、自动补 ``sources/``、禁止 ``..`` 与绝对路径。
    """
    if path_prefix is None:
        return None, None
    raw = str(path_prefix).strip()
    if not raw:
        return None, None

    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        return None, "path_prefix must be a relative path under sources/"

    # Normalize separators without resolving against a real filesystem.
    candidate = raw.replace("\\", "/")
    parts = PurePosixPath(candidate).parts
    if ".." in parts or parts[:1] == ("/",):
        return None, "path_prefix must not contain '..' or escape sources/"

    joined = "/".join(p for p in parts if p not in ("", "."))
    if not joined:
        return None, "path_prefix is empty after normalization"

    if joined == SOURCES_ROOT or joined.startswith(f"{SOURCES_ROOT}/"):
        normalized = joined.rstrip("/")
    else:
        normalized = f"{SOURCES_ROOT}/{joined}".rstrip("/")

    if normalized != SOURCES_ROOT and not normalized.startswith(f"{SOURCES_ROOT}/"):
        return None, "path_prefix must stay under sources/"

    return normalized, None


def path_matches_prefix(path: str, prefix: str) -> bool:
    """path 等于 prefix 或其子孙路径时为 True。"""
    p = path.replace("\\", "/").rstrip("/")
    pref = prefix.replace("\\", "/").rstrip("/")
    if not pref:
        return True
    return p == pref or p.startswith(pref + "/")


def filter_hits_by_path_prefix(
    hits: list[Any],
    *,
    path_prefix: str | None,
) -> tuple[list[Any], dict[str, Any]]:
    """按 path_prefix 过滤 hit 列表；非法 prefix 时返回空列表与 hint。"""
    normalized, err = normalize_path_prefix(path_prefix)
    meta: dict[str, Any] = {}
    if err:
        meta["filters"] = {"path_prefix": path_prefix, "applied": False, "error": err}
        meta["hint"] = err
        return [], meta
    if normalized is None:
        return hits, meta

    meta["filters"] = {"path_prefix": normalized, "applied": True}
    filtered: list[Any] = []
    for hit in hits:
        path = getattr(hit, "path", None)
        if path is None and isinstance(hit, dict):
            path = hit.get("path", "")
        if path_matches_prefix(str(path or ""), normalized):
            filtered.append(hit)
    return filtered, meta
