"""子 agent 委托运行时上下文（ContextVar）。

父 Turn 在执行 ``delegate`` 前通过 ``set_delegate_runtime`` 注入 gateway、Profile、
工具列表、事件写入与取消检查等依赖；嵌套 ``run_delegate`` 通过 ContextVar 读取，
并用 ``delegate_depth`` 限制嵌套层数（见 ``delegate_runner.MAX_DELEGATE_DEPTH``）。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
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
    """父 Turn 侧注入的子 agent 运行所需不可变快照。

    属性:
        gateway: 模型网关，供嵌套 AgentEngine 调用 LLM。
        parent_profile: 父 scenario Profile（含 subagent_types、prompt_suffix 等）。
        parent_tools: 父 Profile 已挂载的 ToolSpec 列表。
        write_event: 事件总线写入回调（子层会 stamp ``subagent_id``）。
        check_cancel: 取消/强杀检查，与父 Turn 共享。
        turn_id/session_id/run_id/trace_id/scenario_id: 追踪与关联 ID。
        hot_files: 父 Turn 热文件路径，写入子 agent prompt。
    """

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
    hot_files: tuple[str, ...] = ()


def set_delegate_runtime(runtime: DelegateRuntime | None) -> None:
    """设置当前异步上下文中的委托运行时；``None`` 表示清除。

    参数:
        runtime: 父 Turn 组装的 ``DelegateRuntime``，或 ``None`` 卸载。
    """
    _delegate_runtime.set(runtime)


def get_delegate_runtime() -> DelegateRuntime | None:
    """读取当前上下文中的委托运行时。

    返回:
        已注入的 ``DelegateRuntime``，未配置时 ``None``。
    """
    return _delegate_runtime.get()


def current_delegate_depth() -> int:
    """返回当前嵌套委托深度（0 表示顶层 Turn）。

    返回:
        整数深度，每进入一层 ``run_delegate`` 递增。
    """
    return _delegate_depth.get()


def bump_delegate_depth() -> Token[int]:
    """进入子 agent 前深度 +1，返回 reset 用 Token。

    返回:
        ``ContextVar.reset`` 所需的 Token，须在 ``finally`` 中传给 ``reset_delegate_depth``。
    """
    return _delegate_depth.set(_delegate_depth.get() + 1)


def reset_delegate_depth(token: Token[int]) -> None:
    """子 agent 结束后恢复委托深度。

    参数:
        token: ``bump_delegate_depth`` 返回的 Token。
    """
    _delegate_depth.reset(token)
