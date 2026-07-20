"""Normalize and apply search_sources path_prefix filters (docs/15)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


SOURCES_ROOT = "sources"


def normalize_path_prefix(path_prefix: str | None) -> tuple[str | None, str | None]:
    """Return (normalized_prefix, error_hint).

    Frozen rules (RE0):
    - None / blank → no filter
    - Relative to workspace; may omit leading ``sources/`` (auto-prefixed)
    - Must stay under ``sources/``; ``..`` and absolute paths are rejected
    - Trailing slashes stripped; empty after normalize → error
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
    """True when ``path`` is exactly ``prefix`` or a descendant."""
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
    """Filter hit objects/dicts by path_prefix.

    Returns (filtered_hits, meta) where meta may include filters + hint on error.
    """
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
