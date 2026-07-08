from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from app.model.gateway import ModelGateway
from app.scenarios.registry import ScenarioProfile
from app.tools.registry import ToolSpec

EventWriter = Callable[..., Awaitable[None]]
CancelChecker = Callable[[], Awaitable[tuple[bool, bool]]]

_delegate_depth: ContextVar[int] = ContextVar("delegate_depth", default=0)
_delegate_runtime: ContextVar[DelegateRuntime | None] = ContextVar("delegate_runtime", default=None)


@dataclass(frozen=True)
class DelegateRuntime:
    gateway: ModelGateway
    parent_profile: ScenarioProfile
    parent_tools: list[ToolSpec]
    write_event: EventWriter
    check_cancel: CancelChecker
    turn_id: UUID
    session_id: UUID
    run_id: UUID
    trace_id: UUID
    scenario_id: str


def set_delegate_runtime(runtime: DelegateRuntime | None) -> None:
    _delegate_runtime.set(runtime)


def get_delegate_runtime() -> DelegateRuntime | None:
    return _delegate_runtime.get()


def current_delegate_depth() -> int:
    return _delegate_depth.get()


def bump_delegate_depth() -> object:
    return _delegate_depth.set(_delegate_depth.get() + 1)


def reset_delegate_depth(token: object) -> None:
    _delegate_depth.reset(token)
