from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CreateSessionRequest(BaseModel):
    default_scenario_id: str = "writing"


class SessionResponse(BaseModel):
    id: UUID
    default_scenario_id: str
    status: str
    created_at: datetime
    owner_user_id: UUID | None = None


class SessionListItem(BaseModel):
    id: UUID
    default_scenario_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    title: str | None = None
    last_user_preview: str | None = None
    last_turn_status: str | None = None


class CreateTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    scenario_id: str | None = None
    mode: str | None = None
    client_request_id: UUID | None = None

    @model_validator(mode="after")
    def _resolve_scenario_alias(self) -> "CreateTurnRequest":
        if self.scenario_id is None and self.mode is not None:
            self.scenario_id = self.mode
        return self


class TurnResponse(BaseModel):
    id: UUID
    session_id: UUID
    scenario_id: str
    status: str
    user_input: str | None = None
    created_at: datetime


class TurnSummary(BaseModel):
    id: UUID
    session_id: UUID
    scenario_id: str
    status: str
    user_input: str | None = None
    latest_output: str | None = None
    created_at: datetime


class TurnView(BaseModel):
    turn_id: UUID
    session_id: UUID
    scenario_id: str
    status: str
    user_input: str
    latest_output: str | None = None
    tool_timeline: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    last_event_sequence: int = 0
    updated_at: datetime
    cancellable: bool = False
    cancel_requested_at: datetime | None = None
    interrupt: dict[str, Any] | None = None
    runner_id: str | None = None
    context_usage: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None


class SessionView(BaseModel):
    session_id: UUID
    default_scenario_id: str
    status: str
    turn_count: int = 0
    last_turn_id: UUID | None = None
    last_turn_status: str | None = None
    context_summary: dict[str, Any] | None = None
    updated_at: datetime


class RunResponse(BaseModel):
    id: UUID
    turn_id: UUID
    status: str
    termination_reason: str | None = None
    runner_id: str | None = None
    cancel_requested_at: datetime | None = None
    cancel_force: bool = False
    created_at: datetime
    updated_at: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MetaBody(BaseModel):
    request_id: UUID


class ErrorResponse(BaseModel):
    data: None = None
    error: ErrorBody
    meta: MetaBody
