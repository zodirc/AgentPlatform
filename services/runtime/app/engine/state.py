"""Turn 运行时状态与 Anthropic 风格消息构造器。

English: Mutable TurnState container and Anthropic-style message builders.

本模块定义单次 Turn 的可变状态容器 ``TurnState``（含 token 用量、取消标志、
读文件覆盖、verify receipt 追踪、写作场景 receipt 等），以及将纯文本/工具调用
组装成 provider 消息 dict 的轻量工厂函数。状态字段会随 checkpoint 序列化，
供 Engine 循环与 ContextEngine 在 assemble 时读取。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.engine.read_registry import PathReadState


@dataclass
class Usage:
    """本 Turn 累计的 LLM token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TurnState:
    """单次 Turn 的全局可变状态；贯穿 Engine 步进、工具执行与 checkpoint 恢复。

    English: All mutable per-turn state — messages, step budget, approval sticky flags,
    read_registry hard gates (docs/34), verify/issue-repro receipts, writing L0 receipts.

    字段按职责分组：身份标识、消息与步数、终止/预算、计划与模式、
    读文件硬门（docs/34）、verify/issue-repro receipt（Wave 4 W9）、
    写作 L0 receipt、以及 StartTurn 用户原文等。
    """

    turn_id: UUID
    session_id: UUID
    run_id: UUID
    trace_id: UUID
    scenario_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    max_steps: int = 40
    usage: Usage = field(default_factory=Usage)
    cancelled: bool = False
    cancel_force: bool = False
    termination_reason: str = "final"
    budget_exceeded: bool = False
    delivery: dict[str, Any] | None = None
    # Intake 可选提示（如多目标 → 建议 update_plan）；从不强制工具。
    plan_hint: str | None = None
    # docs/25 — planning | executing | None（普通 Agent）。
    plan_phase: str | None = None
    # docs/29 — ops_eval 每 Turn 的 model_mode；approve/deny checkpoint 恢复后仍保留。
    model_mode: str | None = None
    # Ops / 官方 L1 StartTurn：无人值守 — 自动批准写/执行类需审批工具。
    ops_eval: bool = False
    # docs/30 WN3/AQ1 — cards/focus/plan 阶段；checkpoint 恢复后保留（不焊进 system）。
    volatile_context: str = ""
    # 用户在本 Turn 批准一次写类工具后，同 Turn 后续 sticky 写操作跳过审批。
    writes_preapproved: bool = False
    # 用户在本 Turn 批准 run_command 后，同 Turn 后续 run_command 跳过审批。
    exec_preapproved: bool = False
    # docs/34 RC1 — Turn 级 read_file 覆盖（read-after-complete 硬门）。
    read_registry: dict[str, PathReadState] = field(default_factory=dict)
    # C1：完整 read 正文已离开可见 assemble 窗口（fold/collapse/snip）的路径。
    # 每路径每 Turn 允许一次重读，不触发 read_after_complete。
    evicted_paths: set[str] = field(default_factory=set)
    evicted_reread_used: set[str] = field(default_factory=set)
    # Wave 4 W9：verify receipt 追踪（仅工具事实；checkpoint 可恢复）。
    verify_pending: bool = False
    verify_receipt_sent: bool = False
    code_edits_since_verify: int = 0
    related_tests_union: list[dict[str, str]] = field(default_factory=list)
    last_repro_command: str = ""
    last_test_first_failure: str = ""
    # Issue 行为复现（problem.md）：仓库测试全绿后的额外门控。
    issue_repro_loaded: bool = False
    issue_repro_commands: list[str] = field(default_factory=list)
    issue_repro_markers: list[str] = field(default_factory=list)
    issue_repro_required_tokens: list[str] = field(default_factory=list)
    issue_repro_assets: list[str] = field(default_factory=list)
    issue_repro_casefold_assets: list[str] = field(default_factory=list)
    issue_repro_fail_signals: list[str] = field(default_factory=list)
    issue_repro_expect_signals: list[str] = field(default_factory=list)
    issue_repro_need_roundtrip: bool = False
    issue_repro_need_casefold: bool = False
    issue_repro_roundtrip_formats: list[str] = field(default_factory=list)
    issue_repro_roundtrip_kwargs: list[str] = field(default_factory=list)
    issue_repro_armed: bool = False
    issue_repro_satisfied: bool = False
    issue_repro_receipt_sent: bool = False
    # 自上次 issue repro 成功以来的代码编辑次数（须为 0 才能保持 satisfied）。
    issue_repro_edits_since: int = 0
    # 本 Turn StartTurn 用户原文（不含后续注入的 receipt）；写作工具从此解析 quota/TOC。
    # 旧 checkpoint 可能为空。
    turn_user_text: str = ""
    # 写作 hinge receipt：看见…立马…却/回头（非章节债）。可 checkpoint。
    hinge_pending: bool = False
    hinge_receipt_sent: bool = False
    # 开篇章「N年前」+失踪/尸体 dump（非章节计数）。可 checkpoint。
    lore_pending: bool = False
    lore_receipt_sent: bool = False
    # 开篇章在可站立场景前写宗/派专名。可 checkpoint。
    opening_pending: bool = False
    opening_receipt_sent: bool = False
    # 均匀短拍（三字问答 / 空应声 / 把因果说圆）。可 checkpoint。
    staccato_pending: bool = False
    staccato_receipt_sent: bool = False
    # 写作 manifest 仍开过程门/篇幅不足时阻止「已完成」叙事（每 Turn 一次）。
    writing_delivery_hold_sent: bool = False


ContentBlock = dict[str, Any]
"""消息 content 数组中的单个块（text / tool_use / tool_result 等）。"""

MessageRole = Literal["user", "assistant", "tool"]
"""Provider 消息角色字面量。"""


def user_message(text: str) -> dict[str, Any]:
    """构造一条纯文本 user 消息。

    参数:
        text: 用户可见正文。

    返回:
        Anthropic/OpenAI 兼容的 ``{"role": "user", "content": [...]}`` dict。
    """
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text: str) -> dict[str, Any]:
    """构造一条仅含文本的 assistant 消息（无 tool_use）。

    参数:
        text: 助手回复正文。

    返回:
        assistant 消息 dict。
    """
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def assistant_tool_use(tool_call_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """构造单工具调用的 assistant 消息。

    参数:
        tool_call_id: 与后续 tool_result 关联的 id。
        tool_name: 注册表中的工具名。
        arguments: 已解析的 JSON 参数字典。

    返回:
        含一个 ``tool_use`` content block 的 assistant 消息。
    """
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tool_call_id,
                "name": tool_name,
                "input": arguments,
            }
        ],
    }


def assistant_tool_uses(tool_calls: list[dict[str, Any]], *, text: str = "") -> dict[str, Any]:
    """构造可含前置文本的多工具并行 assistant 消息。

    参数:
        tool_calls: 每项含 ``id``、``name``、可选 ``input`` 的调用描述。
        text: 可选；非空时在 tool_use 块之前插入 text 块。

    返回:
        合并 text 与多个 tool_use 的 assistant 消息。
    """
    content: list[dict[str, Any]] = []
    if text.strip():
        content.append({"type": "text", "text": text})
    content.extend(
        {
            "type": "tool_use",
            "id": call["id"],
            "name": call["name"],
            "input": call.get("input", {}),
        }
        for call in tool_calls
    )
    return {"role": "assistant", "content": content}


def tool_result_message(tool_call_id: str, result: str, is_error: bool = False) -> dict[str, Any]:
    """构造 tool 角色消息，回传某次 tool_use 的执行结果。

    参数:
        tool_call_id: 对应的 assistant tool_use id。
        result: 序列化后的结果字符串（常为 JSON）。
        is_error: 为 True 时标记 provider 侧为错误结果。

    返回:
        tool 消息 dict。
    """
    return {
        "role": "tool",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result,
                "is_error": is_error,
            }
        ],
    }
