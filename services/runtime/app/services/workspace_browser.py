from __future__ import annotations

import re
from pathlib import Path

from app.tools.core.tools import list_dir, read_file, write_file

MAX_SOURCE_BYTES = 1_048_576  # 1 MiB
_SAFE_SOURCE_NAME = re.compile(r"^[a-zA-Z0-9_\-\.\u4e00-\u9fff]+$")


def safe_source_filename(name: str) -> str:
    base = Path(name or "").name.strip()
    if not base or base in {".", ".."}:
        raise ValueError("invalid filename")
    if not _SAFE_SOURCE_NAME.match(base):
        raise ValueError("filename contains unsupported characters")
    return base


def source_rel_path(filename: str) -> str:
    return f"sources/{safe_source_filename(filename)}"


async def list_workspace_entries(path: str = ".") -> dict:
    return await list_dir(path)


async def read_workspace_file(path: str) -> dict:
    return await read_file(path)


async def write_workspace_file(*, path: str, content: str) -> dict:
    normalized = path.strip().lstrip("/")
    if not normalized.startswith("sources/"):
        raise ValueError("only sources/ paths are writable from web upload")
    filename = Path(normalized).name
    safe_source_filename(filename)
    if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"content exceeds {MAX_SOURCE_BYTES} bytes")
    return await write_file(normalized, content)


async def upload_source_file(*, filename: str, content: str) -> dict:
    rel = source_rel_path(filename)
    written = await write_workspace_file(path=rel, content=content)
    from app.tools.core.tools import sync_sources_index

    index = await sync_sources_index()
    return {**written, "index": index}
