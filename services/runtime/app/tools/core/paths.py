from __future__ import annotations

from pathlib import Path

from app.settings import settings

def _normalized_workspace_rel(rel_path: str) -> str:
    return rel_path.strip().lstrip("/").replace("\\", "/")


def is_seed_corpus_path(rel_path: str) -> bool:
    """True for standing seed corpus under sources/seed/ (RO mount; docs/15)."""
    normalized = _normalized_workspace_rel(rel_path)
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def _resolve_path(rel_path: str) -> Path:
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
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def _assert_not_seed_corpus(rel_path: str) -> None:
    if is_seed_corpus_path(rel_path):
        raise PermissionError(
            "seed corpus is read-only; edit files under seed/sources/writing in the repo"
        )
