"""工作区路径解析：相对路径规范化、seed corpus 只读与越界拦截。

``_resolve_path`` 按当前 Work 根解析；``sources/seed/**`` 映射至部署级
``workspace_root`` 且需 ``current_visibility_seed()`` 开启。
"""

from __future__ import annotations

from pathlib import Path

from app.settings import settings

def _normalized_workspace_rel(rel_path: str) -> str:
    """规范化工作区相对路径：去首尾空白、前导 ``/`` 与反斜杠。"""
    return rel_path.strip().lstrip("/").replace("\\", "/")


def is_seed_corpus_path(rel_path: str) -> bool:
    """判断是否为 ``sources/seed`` 下只读 standing seed 语料（docs/15）。"""
    normalized = _normalized_workspace_rel(rel_path)
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def _resolve_path(rel_path: str) -> Path:
    """解析相对路径为绝对 ``Path``；seed 语料走部署根，否则当前 Work 根。

    越界（``relative_to`` 失败）或 seed 不可见时抛出 ``PermissionError``。
    """
    from app.tenant_context import current_visibility_seed, current_work_root_path

    root = current_work_root_path()
    # Seed corpus is a standing RO mount under the deploy workspace (docs/15 / docs/27).
    if is_seed_corpus_path(rel_path):
        if not current_visibility_seed():
            raise PermissionError(
                "product seed corpus is disabled for this Work "
                "(settings → 使用产品种子语料)"
            )
        root = Path(settings.workspace_root).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path outside workspace: {rel_path}") from exc
    return target


def _workspace_root() -> Path:
    """返回当前 Turn 的工作区根目录（tenant context）。"""
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def _assert_not_seed_corpus(rel_path: str) -> None:
    """写工具前置检查：seed 语料只读，试图写入时抛 ``PermissionError``。"""
    if is_seed_corpus_path(rel_path):
        raise PermissionError(
            "seed corpus is read-only; edit files under seed/sources/writing in the repo"
        )


def workspace_not_writable_error(rel_path: str, exc: BaseException) -> dict[str, str]:
    """Permission denied on the work root — deploy perms, not a product file ban."""
    return {
        "status": "error",
        "error": "workspace_not_writable",
        "path": rel_path,
        "summary": (
            f"Permission denied writing {rel_path} ({exc}). "
            "Not a policy ban on outline.md or drafts/. "
            "Run `make fix-workspace-sources` so /workspace is writable by uid 1000."
        ),
    }
