"""Per-Turn TenantContext (docs/27) — frozen at StartTurn; tools read via ContextVar."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.settings import settings

_work_root: ContextVar[str | None] = ContextVar("tenant_work_root", default=None)
_work_id: ContextVar[UUID | None] = ContextVar("tenant_work_id", default=None)
_owner_user_id: ContextVar[UUID | None] = ContextVar("tenant_owner_user_id", default=None)
_tenant_id: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)
_visibility_seed: ContextVar[bool] = ContextVar("tenant_visibility_seed", default=True)
_resolved_at: ContextVar[str | None] = ContextVar("tenant_resolved_at", default=None)


@dataclass(frozen=True)
class TenantContext:
    """Frozen Intake snapshot — never inject full object into model messages."""

    tenant_id: UUID | None  # personal tenancy: same as owner_user_id
    principal_id: UUID | None  # = owner_user_id (docs/16)
    work_id: UUID | None
    work_root: str
    visibility_seed: bool
    resolved_at: str


_BindTokens = tuple[Token, Token, Token, Token, Token, Token]


def bind_tenant_context(
    *,
    work_root: str | None,
    work_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    tenant_id: UUID | None = None,
    visibility_seed: bool = True,
    resolved_at: str | None = None,
) -> _BindTokens:
    root = (work_root or settings.workspace_root).strip() or settings.workspace_root
    # Personal tenant: tenant_id := owner (no Org table in Wave A).
    tid = tenant_id if tenant_id is not None else owner_user_id
    resolved = resolved_at or datetime.now(timezone.utc).isoformat()
    return (
        _work_root.set(root),
        _work_id.set(work_id),
        _owner_user_id.set(owner_user_id),
        _tenant_id.set(tid),
        _visibility_seed.set(bool(visibility_seed)),
        _resolved_at.set(resolved),
    )


def reset_tenant_context(tokens: _BindTokens) -> None:
    t_root, t_id, t_owner, t_tenant, t_seed, t_resolved = tokens
    _work_root.reset(t_root)
    _work_id.reset(t_id)
    _owner_user_id.reset(t_owner)
    _tenant_id.reset(t_tenant)
    _visibility_seed.reset(t_seed)
    _resolved_at.reset(t_resolved)


def current_tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=_tenant_id.get(),
        principal_id=_owner_user_id.get(),
        work_id=_work_id.get(),
        work_root=current_work_root(),
        visibility_seed=bool(_visibility_seed.get()),
        resolved_at=_resolved_at.get() or "",
    )


def current_work_root() -> str:
    return _work_root.get() or settings.workspace_root


def current_work_root_path() -> Path:
    return Path(current_work_root()).resolve()


def current_work_id() -> UUID | None:
    return _work_id.get()


def current_owner_user_id() -> UUID | None:
    return _owner_user_id.get()


def current_tenant_id() -> UUID | None:
    return _tenant_id.get()


def current_visibility_seed() -> bool:
    return bool(_visibility_seed.get())


def ensure_work_root_exists() -> Path:
    root = current_work_root_path()
    root.mkdir(parents=True, exist_ok=True)
    # Expose standing seed corpus inside isolated works (docs/15 · docs/27).
    legacy = Path(settings.workspace_root).resolve()
    if root != legacy:
        seed_src = legacy / "sources" / "seed"
        seed_dst = root / "sources" / "seed"
        if seed_src.is_dir() and not seed_dst.exists():
            seed_dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                seed_dst.symlink_to(seed_src, target_is_directory=True)
            except OSError:
                pass
    return root
