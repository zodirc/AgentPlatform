"""Resolve a workspace-relative path for HTTP download (full bytes, no truncate)."""

from __future__ import annotations

from pathlib import Path

# Hard cap so a single download cannot pin the proxy (docs/32 cloud takeaway).
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


def resolve_download_target(path: str) -> Path:
    """Return an on-disk file path inside the current Work (or seed when visible).

    Raises:
        ValueError: empty path / not a file / too large
        PermissionError: outside work root or seed hidden (via ``_resolve_path``)
        FileNotFoundError: missing
    """
    from app.tools.core.tools import _resolve_path

    raw = (path or "").strip().lstrip("/")
    if not raw or raw == ".":
        raise ValueError("path is required")
    target = _resolve_path(raw)
    if not target.exists():
        raise FileNotFoundError(f"not found: {raw}")
    if not target.is_file():
        raise ValueError("only files can be downloaded")
    size = target.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"file exceeds download limit ({MAX_DOWNLOAD_BYTES} bytes)"
        )
    return target
