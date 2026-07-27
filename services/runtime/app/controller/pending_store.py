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
    state: TurnState
    profile: ScenarioProfile
    tools: list[ToolSpec]
    gateway: ModelGateway
    trace_id: UUID
    pending_tool_call: dict[str, Any] | None = None
    system_prompt: str = ""
    volatile_context: str = ""


# B9-①: abandoned approvals must not pin full messages + gateway + tools in
# memory forever. Expired entries are recoverable from the step checkpoint
# (approve/deny fall back to _pending_from_checkpoint), so eviction is safe.
_store: dict[UUID, tuple[PendingTurn, float]] = {}


def _ttl_seconds() -> float:
    from app.settings import settings

    return float(getattr(settings, "pending_store_ttl_seconds", 1800.0))


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [turn_id for turn_id, (_, deadline) in _store.items() if deadline <= now]
    for turn_id in expired:
        _store.pop(turn_id, None)


def save(turn_id: UUID, pending: PendingTurn) -> None:
    _purge_expired()
    _store[turn_id] = (pending, time.monotonic() + _ttl_seconds())


def pop(turn_id: UUID) -> PendingTurn | None:
    _purge_expired()
    entry = _store.pop(turn_id, None)
    return entry[0] if entry is not None else None


def get(turn_id: UUID) -> PendingTurn | None:
    _purge_expired()
    entry = _store.get(turn_id)
    return entry[0] if entry is not None else None
