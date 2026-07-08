from __future__ import annotations

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


_store: dict[UUID, PendingTurn] = {}


def save(turn_id: UUID, pending: PendingTurn) -> None:
    _store[turn_id] = pending


def pop(turn_id: UUID) -> PendingTurn | None:
    return _store.pop(turn_id, None)


def get(turn_id: UUID) -> PendingTurn | None:
    return _store.get(turn_id)
