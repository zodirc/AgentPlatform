"""Per-Turn TenantContext（docs/27）：StartTurn 冻结，工具经 ContextVar 读取。

English: Per-turn tenant context (docs/27) — frozen at StartTurn, read via ContextVar in tools.

``work_root`` / ``work_id`` / ``owner_user_id`` / ``visibility_seed`` 在 Turn 入口
``bind_tenant_context`` 绑定，handler 通过 getter 读取；**禁止**注入模型消息。
"""

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
_ops_eval: ContextVar[bool] = ContextVar("tenant_ops_eval", default=False)


@dataclass(frozen=True)
class TenantContext:
    """StartTurn 冻结的租户快照（docs/27）；禁止注入模型消息。

    English: Immutable tenant snapshot for one turn execution.
    """


    tenant_id: UUID | None  # personal tenancy: same as owner_user_id
    principal_id: UUID | None  # = owner_user_id (docs/16)
    work_id: UUID | None
    work_root: str
    visibility_seed: bool
    resolved_at: str


_BindTokens = tuple[Token, Token, Token, Token, Token, Token, Token]


def bind_tenant_context(
    *,
    work_root: str | None,
    work_id: UUID | None = None,
    owner_user_id: UUID | None = None,
    tenant_id: UUID | None = None,
    visibility_seed: bool = True,
    resolved_at: str | None = None,
    ops_eval: bool = False,
) -> _BindTokens:
    """绑定 work_root/work_id/owner 等到 ContextVar。

    English: Bind tenant fields for the current async context (one turn or approval resume).

    参数:
        work_root: 沙箱根路径；None 时用 settings 默认。
        work_id / owner_user_id / tenant_id: Work 与账户标识。
        visibility_seed: 是否可见产品 seed 语料。
        resolved_at: 可选 ISO 时间戳审计字段。
        ops_eval: 评测 Turn 标记。

    返回:
        Token 元组，供 ``reset_tenant_context`` 恢复。
    """
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
        _ops_eval.set(bool(ops_eval)),
    )


def reset_tenant_context(tokens: _BindTokens) -> None:
    """作用：恢复 bind 前的租户 ContextVar。"""
    t_root, t_id, t_owner, t_tenant, t_seed, t_resolved, t_ops = tokens
    _work_root.reset(t_root)
    _work_id.reset(t_id)
    _owner_user_id.reset(t_owner)
    _tenant_id.reset(t_tenant)
    _visibility_seed.reset(t_seed)
    _resolved_at.reset(t_resolved)
    _ops_eval.reset(t_ops)


def current_ops_eval() -> bool:
    """作用：当前 Turn 是否为 Ops eval（影响 sandbox 网络）。"""
    return bool(_ops_eval.get())


def sandbox_network_allowed() -> bool:
    """作用：Ops deny-network 激活时返回 False。"""
    if settings.ops_eval_deny_network and current_ops_eval():
        return False
    return True


def current_tenant_context() -> TenantContext:
    """作用：组装 TenantContext 不可变快照。"""
    return TenantContext(
        tenant_id=_tenant_id.get(),
        principal_id=_owner_user_id.get(),
        work_id=_work_id.get(),
        work_root=current_work_root(),
        visibility_seed=bool(_visibility_seed.get()),
        resolved_at=_resolved_at.get() or "",
    )


def current_work_root() -> str:
    """作用：当前 Work 根路径字符串。"""
    return _work_root.get() or settings.workspace_root


def current_work_root_path() -> Path:
    """作用：resolve 后的 Path。"""
    return Path(current_work_root()).resolve()


def current_work_id() -> UUID | None:
    """作用：当前 Work UUID。"""
    return _work_id.get()


def current_owner_user_id() -> UUID | None:
    """作用：Work 所有者 principal UUID。"""
    return _owner_user_id.get()


def current_tenant_id() -> UUID | None:
    """作用：租户 ID（个人租户=owner）。"""
    return _tenant_id.get()


def current_visibility_seed() -> bool:
    """作用：是否展示 seed 挂载。"""
    return bool(_visibility_seed.get())


def ensure_work_root_exists() -> Path:
    """作用：创建 Work 根；隔离 Work 确保 sources/seed 目录。"""
    root = current_work_root_path()
    root.mkdir(parents=True, exist_ok=True)
    # Isolated Works need a real ``sources/seed`` directory so list_dir (which
    # does not follow symlinks) still advertises a folder. Child reads remap
    # to the deploy mount via ``_resolve_path`` (docs/15 · docs/27).
    legacy = Path(settings.workspace_root).resolve()
    if root != legacy:
        seed_src = legacy / "sources" / "seed"
        seed_dst = root / "sources" / "seed"
        if seed_src.is_dir():
            seed_dst.parent.mkdir(parents=True, exist_ok=True)
            if seed_dst.is_symlink():
                try:
                    seed_dst.unlink()
                except OSError:
                    pass
            if not seed_dst.exists():
                try:
                    seed_dst.mkdir(exist_ok=True)
                except OSError:
                    pass
    return root
