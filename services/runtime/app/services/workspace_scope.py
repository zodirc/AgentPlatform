
"""内部 API 用 workspace_tenant_scope 绑定 TenantContext（MT5c）。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID


@contextmanager
def workspace_tenant_scope(
    *,
    work_id: str | None = None,
    work_root: str | None = None,
    owner_user_id: str | None = None,
    visibility_seed: str | bool | None = None,
) -> Iterator[None]:
    """作用：workspace_tenant_scope 公开 API。"""
    from app.tenant_context import (
        bind_tenant_context,
        ensure_work_root_exists,
        reset_tenant_context,
    )

    wid = UUID(work_id) if work_id else None
    oid = UUID(owner_user_id) if owner_user_id else None
    if visibility_seed is None:
        seed_ok = True
    elif isinstance(visibility_seed, bool):
        seed_ok = visibility_seed
    else:
        seed_ok = str(visibility_seed).strip().lower() in {"1", "true", "yes", "on"}
    tokens = bind_tenant_context(
        work_root=work_root,
        work_id=wid,
        owner_user_id=oid,
        visibility_seed=seed_ok,
    )
    try:
        if work_root:
            ensure_work_root_exists()
        yield
    finally:
        reset_tenant_context(tokens)
