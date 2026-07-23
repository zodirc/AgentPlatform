from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PlanPhase = Literal["planning", "executing"]
ModelMode = Literal["stub", "live", "recorded"]


class ModelOverride(BaseModel):
    """Per-Turn live model credentials (docs/29 ops eval). Never from public Web turns."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    context_window_tokens: int | None = Field(default=None, ge=4096, le=2_000_000)


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
    # docs/27 — TenantContext snapshot (optional for back-compat callers; api always sends).
    work_id: UUID | None = None
    work_root: str | None = Field(default=None, min_length=1, max_length=1024)
    owner_user_id: UUID | None = None
    # docs/29 — per-Turn model mode (null = process MODEL_MODE)
    model_mode: ModelMode | None = None
    model_override: ModelOverride | None = None
    # When true, runtime accepts model_mode/model_override (api ops eval only).
    ops_eval: bool = False


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
