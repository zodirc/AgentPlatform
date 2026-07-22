"""Bind TenantContext for internal workspace / Sources APIs (docs/27 MT5c)."""

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
) -> Iterator[None]:
    """Scope filesystem tools to a Work root when api forwards tenant fields."""
    from app.tenant_context import (
        bind_tenant_context,
        ensure_work_root_exists,
        reset_tenant_context,
    )

    wid = UUID(work_id) if work_id else None
    oid = UUID(owner_user_id) if owner_user_id else None
    tokens = bind_tenant_context(
        work_root=work_root,
        work_id=wid,
        owner_user_id=oid,
    )
    try:
        if work_root:
            ensure_work_root_exists()
        yield
    finally:
        reset_tenant_context(tokens)
