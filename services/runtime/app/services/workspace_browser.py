from __future__ import annotations

from app.tools.core.tools import list_dir, read_file


async def list_workspace_entries(path: str = ".") -> dict:
    return await list_dir(path)


async def read_workspace_file(path: str) -> dict:
    return await read_file(path)
