from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PlanPhase = Literal["planning", "executing"]


class StartTurnCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    run_id: UUID
    session_id: UUID
    scenario_id: str = Field(pattern=r"^(writing|agent|interview)$")
    message: str = Field(min_length=1)
    client_request_id: UUID | None = None
    trace_id: UUID
    # Omit / null = normal Agent (default path). See docs/25.
    plan_phase: PlanPhase | None = None


class CancelTurnCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    run_id: UUID
    trace_id: UUID
    reason: str = "user_requested"
    force: bool = False


class ApproveToolCallCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    run_id: UUID
    tool_call_id: str = Field(min_length=1)
    trace_id: UUID


class DenyToolCallCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    run_id: UUID
    tool_call_id: str = Field(min_length=1)
    trace_id: UUID
    reason: str = "user_denied"
