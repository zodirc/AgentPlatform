
"""HTTP 下载：解析 workspace 相对路径为完整文件字节。"""

from __future__ import annotations

from pathlib import Path

# Hard cap so a single download cannot pin the proxy (docs/32 cloud takeaway).
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


def resolve_download_target(path: str) -> Path:
    """作用：resolve_download_target 公开 API。

参数：
    ``path``"""
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
