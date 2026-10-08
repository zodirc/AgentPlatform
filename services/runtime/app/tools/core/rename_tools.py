"""工作区文件重命名。与编码 LSP / AST 模块分开，写作注册表可单独导入。"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.core.paths import (
    _assert_not_seed_corpus,
    _normalized_workspace_rel,
    _resolve_path,
    _workspace_root,
)

logger = logging.getLogger(__name__)


async def rename_file(
    path: str,
    new_path: str,
    *,
    overwrite: bool = False,
    **_kwargs: Any,
) -> dict[str, Any]:
    """重命名或移动工作区内的单个文件（非目录、非 export）。"""
    src_rel = _normalized_workspace_rel(path)
    dst_rel = _normalized_workspace_rel(new_path)
    if not src_rel or not dst_rel:
        return {"status": "error", "error": "path and new_path are required"}
    if src_rel == dst_rel:
        return {
            "status": "ok",
            "path": src_rel,
            "new_path": dst_rel,
            "summary": f"Already named {dst_rel}",
        }

    try:
        _assert_not_seed_corpus(src_rel)
        _assert_not_seed_corpus(dst_rel)
        src = _resolve_path(src_rel)
        dst = _resolve_path(dst_rel)
    except PermissionError as exc:
        return {"status": "error", "error": str(exc)}

    if not src.exists():
        return {"status": "error", "error": f"File not found: {src_rel}"}
    if not src.is_file():
        return {
            "status": "error",
            "error": f"Not a file (directories unsupported): {src_rel}",
        }
    if dst.exists() and not overwrite:
        return {
            "status": "error",
            "error": f"Destination exists: {dst_rel}; pass overwrite=true to replace",
        }
    if dst.exists() and overwrite and dst.is_dir():
        return {"status": "error", "error": f"Destination is a directory: {dst_rel}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        dst.unlink()
    src.rename(dst)
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        oid = str(owner) if owner else None
        wid = current_work_id()
        root = _workspace_root()
        notify_path_changed(
            src_rel, work_id=wid, owner_user_id=oid, work_root=root, deleted=True
        )
        notify_path_changed(dst_rel, work_id=wid, owner_user_id=oid, work_root=root)
    except Exception:
        logger.warning(
            "workspace_ast dirty notify failed rename %s -> %s",
            src_rel,
            dst_rel,
            exc_info=True,
        )
    return {
        "status": "renamed",
        "path": src_rel,
        "new_path": dst_rel,
        "summary": f"Renamed {src_rel} → {dst_rel}",
    }
