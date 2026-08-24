"""HTTP API 请求/响应 Pydantic 契约模型。

与 OpenAPI ``response_model`` 及路由请求体对齐；``ErrorResponse`` 为统一错误包络。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


PlanPhase = Literal["planning", "executing"]
"""Plan 轨道阶段：planning 规划 / executing 执行。"""


class CreateSessionRequest(BaseModel):
    """创建会话请求体。"""

    default_scenario_id: str = "writing"
    work_id: UUID | None = None


class BulkDeleteSessionsRequest(BaseModel):
    """批量删除会话请求（1–100 个 id）。"""

    session_ids: list[UUID] = Field(min_length=1, max_length=100)


class BulkDeleteSessionsResponse(BaseModel):
    """批量删除结果：已删与未找到的 session id。"""

    deleted: list[UUID]
    missing: list[UUID]


class SessionResponse(BaseModel):
    """单条会话资源响应。"""

    id: UUID
    default_scenario_id: str
    status: str
    created_at: datetime
    owner_user_id: UUID | None = None
    work_id: UUID | None = None


class SessionListItem(BaseModel):
    """会话列表项（含摘要字段）。"""

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
    """在会话内创建 turn 的请求体。"""

    message: str = Field(min_length=1)
    scenario_id: str | None = None
    mode: str | None = None
    client_request_id: UUID | None = None
    # docs/25 — omit for normal Agent; planning | executing for Plan track.
    plan_phase: PlanPhase | None = None

    @model_validator(mode="after")
    def _resolve_scenario_alias(self) -> "CreateTurnRequest":
        """``mode`` 为 ``scenario_id`` 的遗留别名。"""
        if self.scenario_id is None and self.mode is not None:
            self.scenario_id = self.mode
        return self


class TurnResponse(BaseModel):
    """Turn 创建/读取的基础响应。"""

    id: UUID
    session_id: UUID
    scenario_id: str
    status: str
    user_input: str | None = None
    created_at: datetime


class TurnSummary(BaseModel):
    """Turn 列表摘要（含 latest_output 与 plan 快照）。"""

    id: UUID
    session_id: UUID
    scenario_id: str
    status: str
    user_input: str | None = None
    latest_output: str | None = None
    created_at: datetime
    # Latest plan artifact from turn_views (for chat-stream multi-plan history).
    plan: dict[str, Any] | None = None


class TurnView(BaseModel):
    """Turn 聚合读模型（投影 ``turn_views``）。"""

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
    """会话聚合读模型（投影 ``session_views``）。"""

    session_id: UUID
    default_scenario_id: str
    status: str
    turn_count: int = 0
    last_turn_id: UUID | None = None
    last_turn_status: str | None = None
    context_summary: dict[str, Any] | None = None
    updated_at: datetime


class RunResponse(BaseModel):
    """Run 资源响应（dispatch/执行单元）。"""

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
    """统一错误体：机器可读 code + 人类 message + 可选 details。"""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MetaBody(BaseModel):
    """响应元数据（request 关联 id）。"""

    request_id: UUID


class ErrorResponse(BaseModel):
    """标准错误 HTTP 响应包络 ``{ data, error, meta }``。"""

    data: None = None
    error: ErrorBody
    meta: MetaBody
