"""审批挂起时的进程内 ``PendingTurn`` 仓库。

English: In-process store for PendingTurn while a turn is waiting_approval.

与 checkpoint 的关系
--------------------
- **本仓库**：TTL 内持有完整 ``gateway`` / ``tools`` / ``volatile_context``，
  approve/deny 热路径优先 ``pop`` 这里，避免重建网关。
- **checkpoint**：落盘 messages + interrupt 元数据；TTL 过期或进程重启后，
  approve/deny 回落 ``_pending_from_checkpoint``，故淘汰内存条目是**安全**的。

B9-①: abandoned approvals must not pin full messages + gateway + tools in
memory forever. Expired entries are recoverable from the step checkpoint
(approve/deny fall back to _pending_from_checkpoint), so eviction is safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.engine.state import TurnState
from app.model.gateway import ModelGateway
from app.scenarios.registry import ScenarioProfile
from app.tools.registry import ToolSpec


@dataclass
class PendingTurn:
    """``waiting_approval`` 时冻结的续跑上下文。

    English: Frozen resume context for a turn paused on tool approval.

    属性:
        state: 含 messages / 验证欠账等的 ``TurnState``。
        profile / tools / gateway: 续跑 Engine 所需绑定（与挂起前一致）。
        trace_id: 观测 ID。
        pending_tool_call: 挂起的 ``tool_use`` 描述（含 ``tool_call_id``）。
        system_prompt / volatile_context: 组窗前缀（WN3：稳定 system vs 易变垫）。
    """

    state: TurnState
    profile: ScenarioProfile
    tools: list[ToolSpec]
    gateway: ModelGateway
    trace_id: UUID
    pending_tool_call: dict[str, Any] | None = None
    system_prompt: str = ""
    volatile_context: str = ""


# B9-①: abandoned approvals must not pin full messages + gateway + tools forever.
# 中文：废弃的审批不得永久钉住 messages+gateway+tools；过期可从 checkpoint 恢复。
_store: dict[UUID, tuple[PendingTurn, float]] = {}


def _ttl_seconds() -> float:
    """pending 条目存活秒数（``settings.pending_store_ttl_seconds``，默认 1800）。"""
    from app.settings import settings

    return float(getattr(settings, "pending_store_ttl_seconds", 1800.0))


def _purge_expired() -> None:
    """删除已过 deadline 的条目（惰性 GC，在 save/get/pop 时触发）。"""
    now = time.monotonic()
    expired = [turn_id for turn_id, (_, deadline) in _store.items() if deadline <= now]
    for turn_id in expired:
        _store.pop(turn_id, None)


def save(turn_id: UUID, pending: PendingTurn) -> None:
    """写入/覆盖本 Turn 的 pending，并刷新 TTL。

    English: Upsert PendingTurn and reset expiry deadline.

    参数:
        turn_id: 键（与 waiting_approval 的 Turn 一致）。
        pending: 完整续跑上下文。
    """
    _purge_expired()
    _store[turn_id] = (pending, time.monotonic() + _ttl_seconds())


def pop(turn_id: UUID) -> PendingTurn | None:
    """取出并删除 pending（approve/deny 热路径）。

    English: Remove and return PendingTurn; None if missing or expired.

    参数:
        turn_id: 键。

    返回:
        ``PendingTurn`` 或 ``None``。
    """
    _purge_expired()
    entry = _store.pop(turn_id, None)
    return entry[0] if entry is not None else None


def get(turn_id: UUID) -> PendingTurn | None:
    """只读查看 pending（不删除）。

    English: Peek PendingTurn without removing it.

    参数:
        turn_id: 键。

    返回:
        ``PendingTurn`` 或 ``None``。
    """
    _purge_expired()
    entry = _store.get(turn_id)
    return entry[0] if entry is not None else None
