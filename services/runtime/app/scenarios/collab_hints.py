"""协作场景 volatile 提示块：编排约束、delegate 缺口与 handoff 软提示。

仅改写 ``volatile_context``，不改变 AgentEngine 主控制流。
"""

from __future__ import annotations

import json
import re
from typing import Any

COLLAB_GAP_MARK = "[collab_gap]"
"""``volatile_context`` 中协作缺口提示段的起始标记，便于 mid-Turn 局部刷新。"""

_EDIT_TYPES = frozenset({"edit", "editor", "drafter"})
_CHECK_TYPES = frozenset({"verify", "shell"})


def collab_orchestrator_block() -> str:
    """生成协作编排 volatile 块：首工具约束、角色混用与简单 Q&A 例外。

    参数:
        无。

    返回:
        以 ``[collab_orchestrator]`` 开头的多行提示文本。
    """
    return (
        "[collab_orchestrator]\n"
        "Orchestration-required (greenfield / multi-deliverable / ≥2 constraints): "
        "first tool MUST be `update_plan` or `delegate` — never `list_dir(\".\")` / "
        "`glob(\"**/*\")` workspace survey.\n"
        "Mix roles: not edit-only — after writes use `verify` or `shell`; "
        "independent files may be parallel `edit`s. Handoff via `context_refs` / "
        "`artifact_refs` (prefer `artifacts/collab/`).\n"
        "Simple Q&A only: answer yourself; zero `delegate`.\n"
    )


def _parse_delegate_payload(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text.startswith("{"):
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def delegate_type_signals(messages: list[dict[str, Any]]) -> tuple[bool, bool]:
    """从本 Turn 消息流推断 delegate 是否已覆盖 edit 与 verify/shell 角色。

    参数:
        messages: Turn 内 OpenAI/Anthropic 风格消息列表（含 tool / assistant）。

    返回:
        ``(saw_edit_delegate, saw_verify_or_shell)`` 二元组。
    """
    saw_edit = False
    saw_check = False
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content")
        raw = ""
        if isinstance(content, str):
            raw = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    raw = str(block.get("content") or "")
                    break
        if "subagent_id" not in raw and "agent_type" not in raw:
            continue
        data = _parse_delegate_payload(raw)
        agent_type = str(data.get("agent_type") or "").strip().lower()
        if not agent_type:
            # Assistant tool_use args may be clearer; fall back to summary heuristics.
            continue
        if agent_type in _EDIT_TYPES:
            saw_edit = True
        if agent_type in _CHECK_TYPES:
            saw_check = True
    # Also scan assistant tool_use for delegate agent_type (before result lands).
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "delegate":
                continue
            args = block.get("input") or {}
            agent_type = str(args.get("agent_type") or "").strip().lower()
            if agent_type in _EDIT_TYPES:
                saw_edit = True
            if agent_type in _CHECK_TYPES:
                saw_check = True
    return saw_edit, saw_check


def apply_collab_gap_hint(volatile: str, messages: list[dict[str, Any]]) -> str:
    """Mid-Turn 刷新协作缺口提示，不重写 ``volatile_context`` 其余内容。

    参数:
        volatile: 当前 volatile 上下文全文。
        messages: 本 Turn 消息列表，供 ``delegate_type_signals`` 扫描。

    返回:
        更新后的 volatile 字符串（末尾保留换行）。
    """
    text = volatile or ""
    if COLLAB_GAP_MARK in text:
        text = text.split(COLLAB_GAP_MARK, 1)[0].rstrip() + "\n"
    saw_edit, saw_check = delegate_type_signals(messages)
    if saw_edit and not saw_check:
        text = (
            f"{text.rstrip()}\n\n{COLLAB_GAP_MARK}\n"
            "Implementation delegates ran without verify/shell yet — "
            "prefer `delegate` agent_type=verify (or shell) for smoke; "
            "pass context_refs to the files just written.\n"
        )
    return text if text.endswith("\n") else text + "\n"


_PATHISH = re.compile(r"\b[\w./-]+\.(?:py|md|json|ts|tsx|js|sh|yml|yaml)\b")


def handoff_prompt_extra(
    *,
    agent_type: str,
    context_refs: list[str] | None,
    paths: list[str] | None,
    task: str,
) -> str:
    """父 agent 未传 ``context_refs`` 时，为 verify/shell 子 agent 追加软 handoff 提示。

    参数:
        agent_type: 子 agent 类型（小写）。
        context_refs: 父级显式传递的上下文路径列表。
        paths: 备用路径列表（与 ``context_refs`` 合并判断）。
        task: 委派任务正文，用于路径正则启发。

    返回:
        追加到子 agent prompt 的 ``[handoff_hint]`` 块；无需提示时为空字符串。
    """
    if agent_type not in _CHECK_TYPES:
        return ""
    refs = [*(context_refs or []), *(paths or [])]
    refs = [str(r).strip() for r in refs if str(r).strip()]
    if refs:
        return ""
    named = _PATHISH.findall(task or "")
    if named:
        return (
            "\n\n[handoff_hint]\n"
            "No context_refs passed; paths mentioned in the task — read those first.\n"
        )
    return (
        "\n\n[handoff_hint]\n"
        "No context_refs passed; locate the deliverable with a narrow read/glob, "
        "then smoke via run_command. Prefer parent passing context_refs next time.\n"
    )
