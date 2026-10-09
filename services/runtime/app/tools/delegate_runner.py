"""子 Agent（delegate）运行器：嵌套 AgentEngine 与工具子集调度。

父 Turn 通过 ``delegate`` 工具 spawn 专注子 agent（researcher/drafter/explore 等）。
本模块负责：深度限制、Profile 白名单、工具解析、prompt 组装、事件转发与产物引用解析。
子 agent 共享父 Turn 的 step 预算。允许名单内的 S2 在子层执行。
其余需要审批的调用带着 ``origin: child/<id>`` 冒泡到父 Turn，批准后 ``child_join`` 恢复该子 Run。
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from app.controller.runtime_context import get_event_writer
from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState, user_message
from app.tools.bootstrap import build_registry

_PARKED_CHILDREN: dict[str, dict[str, Any]] = {}
from app.tools.delegate_context import (
    bump_delegate_depth,
    current_delegate_depth,
    get_delegate_runtime,
    reset_delegate_depth,
)
from app.tools.registry import ToolSpec

MAX_DELEGATE_DEPTH = 2
# Nested engines share the parent Turn budget; 8 was too tight for edit+smoke.
DEFAULT_SUBAGENT_MAX_STEPS = 12

_ARTIFACT_REFS_LINE = re.compile(r"(?im)^\s*ARTIFACT_REFS\s*:\s*(.+)$")

SUBAGENT_TOOL_NAMES: dict[str, list[str]] = {
    "researcher": ["read_file", "list_dir", "search_sources", "grep"],
    "drafter": ["read_file", "draft_section", "update_outline", "propose_patch"],
    "editor": ["read_file", "propose_patch", "edit_file", "write_file", "rename_file"],
    "fact_checker": ["read_file", "check_citation", "search_sources"],
    "stylist": ["read_file", "draft_section", "propose_patch"],
    "explore": [
        "read_file",
        "list_dir",
        "grep",
        "glob",
        "search_codebase",
        "search_sources",
        "goto_definition",
        "find_references",
    ],
    "retrieve": [
        "read_file",
        "search_sources",
        "search_codebase",
        "list_dir",
        "goto_definition",
        "find_references",
    ],
    "verify": [
        "read_file",
        "check_citation",
        "read_lints",
        "find_references",
        "run_tests",
        "run_command",
    ],
    "edit": [
        "read_file",
        "write_file",
        "edit_file",
        "rename_file",
        "goto_definition",
        "find_references",
        "read_lints",
    ],
    "planner": ["read_file", "list_dir", "update_plan", "grep"],
    "shell": ["read_file", "grep", "run_command"],
}

# Parent projection / meters must not absorb sub-agent side effects.
# Live UI events are forwarded with subagent_id stamped (nested readonly chat).
_SUPPRESSED_SUB_EVENTS = frozenset(
    {
        "section.draft.delta",
        "retrieval.completed",
        "patch.proposed",
        "outline.updated",
        "turn.plan",
        "opening.ponds",
        "cards.pinned",
        "context.reported",
        "usage.reported",
    }
)


def _allowed_subagent_types(scenario_id: str, profile_types: list[str]) -> frozenset[str]:
    """解析当前 scenario 允许的 subagent 类型集合。

    参数:
        scenario_id: 场景 ID，仅用于错误信息。
        profile_types: Profile YAML 中的 ``subagent_types`` 列表。

    返回:
        允许的类型名 frozenset。

    说明:
        空列表直接 ``ValueError``——不再保留硬编码默认，必须由 profiles/*.yaml 配置。
    """
    if profile_types:
        return frozenset(profile_types)
    raise ValueError(
        f"scenario {scenario_id!r} has empty subagent_types in Profile "
        "(configure profiles/*.yaml; hard-coded defaults removed)"
    )


def _resolve_sub_tools(parent_tools: list[ToolSpec], agent_type: str) -> list[ToolSpec]:
    """为指定 subagent 类型解析可用 ToolSpec 列表。

    参数:
        parent_tools: 父 Profile 已挂载的工具规格。
        agent_type: 子 agent 类型键（见 ``SUBAGENT_TOOL_NAMES``）。

    返回:
        子代理可见的工具。审批标志保持原样，不在这里关掉。

    说明:
        - ``goto_definition``/``find_references`` 仅当父 Profile 已包含时才注入，不从全局 registry 偷渡。
        - 其它工具优先父列表，缺失时回退 ``build_registry()`` 全局查找。
        - 不在允许名单里的调用由执行器冒泡，origin 为 ``child/<id>``。
    """
    by_name = {spec.name: spec for spec in parent_tools}
    registry = None
    specs: list[ToolSpec] = []
    structural_nav = frozenset({"goto_definition", "find_references"})
    for name in SUBAGENT_TOOL_NAMES.get(agent_type, []):
        # Nav tools only when already on the parent Profile scope (agent).
        # Never inject from the global registry into writing.
        if name in structural_nav:
            if name not in by_name:
                continue
            specs.append(by_name[name])
            continue
        if name in by_name:
            specs.append(by_name[name])
            continue
        if registry is None:
            registry = build_registry()
        found = registry.get(name)
        if found is not None:
            specs.append(found)
    # Reads, reversible writes, and S2. Off-list commands are not pre-approved;
    # the executor bubbles those to the parent turn.
    kept: list[ToolSpec] = []
    for spec in specs:
        sink = str(getattr(spec, "sink_class", "") or "")
        if sink in {"S0", "S1", "S2"}:
            kept.append(spec)
    return kept


async def run_delegate(
    *,
    task: str,
    agent_type: str = "explore",
    context: str = "",
    context_refs: list[str] | None = None,
    paths: list[str] | None = None,
    turn_id: UUID | None = None,
    run_id: UUID | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """执行一次子 agent 委托：spawn 嵌套 AgentEngine 并返回摘要。

    参数:
        task: 子 agent 要完成的具体任务描述。
        agent_type: 子 agent 类型，须在 scenario Profile 的 ``subagent_types`` 内。
        context: 可选附加上下文（截断至 2000 字符；大材料应走 ``context_refs``/``paths``）。
        context_refs: 建议子 agent 优先 ``read_file`` 的路径指针列表。
        paths: 与 ``context_refs`` 合并归一化的路径列表（兼容旧参数名）。
        turn_id: 父 Turn ID（必填）。
        run_id: 父 Run ID（必填）。

    返回:
        含 ``subagent_id``/``agent_type``/``summary``/``artifact_refs``/``status`` 的 dict。
        ``status`` 为 ``completed``/``cancelled``/``failed``；深度超限、类型不允许、无工具等亦返回 ``failed``。
    """
    ctx = get_delegate_runtime()
    if ctx is None:
        return {"status": "failed", "error": "delegate runtime not configured"}

    if current_delegate_depth() >= MAX_DELEGATE_DEPTH:
        return {"status": "failed", "error": "max delegate depth exceeded"}

    allowed = _allowed_subagent_types(ctx.scenario_id, list(ctx.parent_profile.subagent_types))
    if agent_type not in allowed:
        return {
            "status": "failed",
            "error": f"agent_type '{agent_type}' not allowed for scenario {ctx.scenario_id}",
        }

    if turn_id is None or run_id is None:
        return {"status": "failed", "error": "missing turn_id or run_id"}

    wait = _kwargs.get("wait", True)
    from app.engine.child_spawn import should_spawn_child

    if should_spawn_child(agent_type=agent_type, wait=wait):
        return {
            "status": "spawn_child",
            "child": {
                "task": task,
                "agent_type": agent_type,
                "context": context,
                "context_refs": list(context_refs or []),
                "paths": list(paths or []),
                "turn_id": str(turn_id),
                "run_id": str(run_id),
            },
            "summary": f"spawned {agent_type} child",
        }

    subagent_id = f"sub-{uuid4().hex[:8]}"
    writer = get_event_writer() or ctx.write_event

    await writer(
        event_type="subagent.started",
        payload={
            "subagent_id": subagent_id,
            "agent_type": agent_type,
            "task": task[:500],
        },
    )

    sub_tools = _resolve_sub_tools(ctx.parent_tools, agent_type)
    if not sub_tools:
        return {"status": "failed", "error": f"no tools available for sub-agent type {agent_type}"}

    prompt = _build_delegate_prompt(
        task=task,
        context=context,
        context_refs=context_refs,
        paths=paths,
        hot_files=list(ctx.hot_files),
    )
    from app.scenarios.collab_hints import handoff_prompt_extra

    prompt = prompt + handoff_prompt_extra(
        agent_type=agent_type,
        context_refs=context_refs,
        paths=paths,
        task=task,
    )
    sub_state = TurnState(
        turn_id=turn_id,
        session_id=ctx.session_id,
        run_id=run_id,
        trace_id=ctx.trace_id,
        scenario_id=ctx.scenario_id,
        messages=[user_message(prompt)],
        max_steps=DEFAULT_SUBAGENT_MAX_STEPS,
    )

    async def sub_write_event(
        *,
        event_type: str,
        payload: dict[str, Any],
        step_index: int | None = None,
    ) -> None:
        if event_type in _SUPPRESSED_SUB_EVENTS:
            return
        stamped = dict(payload)
        stamped["subagent_id"] = subagent_id
        if event_type == "approval.requested":
            stamped["origin"] = f"child/{subagent_id}"
        await ctx.write_event(
            event_type=event_type, payload=stamped, step_index=step_index
        )

    depth_token = bump_delegate_depth()
    try:
        suffix = (ctx.parent_profile.subagent_prompt_suffix or "").strip()
        collab_board = f" {suffix}" if suffix else ""
        engine = AgentEngine(
            gateway=ctx.gateway,
            tools=sub_tools,
            system_prompt=(
                f"You are a focused {agent_type} sub-agent. "
                "Complete the delegated task using tools; return a concise factual summary. "
                "Prefer read_file on [context_refs] / [hot_files] paths instead of inventing paths "
                f"or pasting large file bodies yourself.{collab_board}"
            ),
            write_event=sub_write_event,
            check_cancel=ctx.check_cancel,
        )
        summary = await engine.run(sub_state)
    finally:
        reset_delegate_depth(depth_token)

    if summary == "waiting_approval":
        pending = dict(getattr(engine, "pending_approval", None) or {})
        _PARKED_CHILDREN[subagent_id] = {"engine": engine, "state": sub_state}
        return {
            "status": "approval_required",
            "origin": f"child/{subagent_id}",
            "subagent_id": subagent_id,
            "summary": "子代理等待审批",
            "window_taint": str(pending.get("window_taint") or getattr(sub_state, "window_taint", "") or ""),
            "sink_class": str(pending.get("sink_class") or ""),
            "child_tool_name": pending.get("tool_name"),
            "child_tool_call_id": pending.get("tool_call_id"),
            "child_arguments": pending.get("arguments") or {},
            "approval_id": pending.get("approval_id"),
            "args_hash": pending.get("args_hash"),
            "policy_version": pending.get("policy_version"),
            "expires_at": pending.get("expires_at"),
            "_taint": str(getattr(sub_state, "window_taint", "") or "workspace"),
        }

    if sub_state.cancelled:
        status = "cancelled"
        summary = summary or "sub-agent cancelled"
    else:
        status = "completed"
        summary = (summary or "sub-agent completed").strip()

    artifact_refs = _extract_artifact_refs(summary)

    await writer(
        event_type="subagent.completed",
        payload={
            "subagent_id": subagent_id,
            "agent_type": agent_type,
            "summary": summary[:500],
        },
    )

    child_taint = "external" if getattr(sub_state, "saw_external", False) else str(
        getattr(sub_state, "window_taint", "workspace") or "workspace"
    )
    return {
        "subagent_id": subagent_id,
        "agent_type": agent_type,
        "summary": summary,
        "artifact_refs": artifact_refs,
        "status": status,
        "window_taint": child_taint,
        "_taint": child_taint,
    }


def _extract_artifact_refs(text: str) -> list[str]:
    """从子 agent 摘要中解析 ``ARTIFACT_REFS: a, b`` 交接行。

    参数:
        text: 子 agent 最终 summary 文本。

    返回:
        最多 12 个本地相对路径（跳过 http URL），供父 agent 黑板引用。
    """
    refs: list[str] = []
    for match in _ARTIFACT_REFS_LINE.finditer(text or ""):
        for part in re.split(r"[,;\n]", match.group(1)):
            path = part.strip().strip("`").strip()
            if not path or path.startswith("http"):
                continue
            if path not in refs:
                refs.append(path)
            if len(refs) >= 12:
                return refs
    return refs


def _normalize_refs(*groups: list[str] | None) -> list[str]:
    """合并多组路径引用并去重，上限 12 条。

    参数:
        *groups: 若干可选路径字符串列表（``None`` 或空列表跳过）。

    返回:
        去重后的路径列表。
    """
    out: list[str] = []
    for group in groups:
        if not group:
            continue
        for item in group:
            path = str(item).strip()
            if path and path not in out:
                out.append(path)
            if len(out) >= 12:
                return out
    return out


def _build_delegate_prompt(
    *,
    task: str,
    context: str,
    context_refs: list[str] | None,
    paths: list[str] | None,
    hot_files: list[str],
) -> str:
    """组装子 agent 用户消息：任务 + 短上下文 + 路径指针块。

    参数:
        task: 主任务文本。
        context: 可选粘贴上下文（已在调用方截断策略内处理）。
        context_refs: 显式上下文文件路径。
        paths: 与 ``context_refs`` 合并的路径。
        hot_files: 父 Turn 热文件列表，格式化为 ``[hot_files]`` 块。

    返回:
        多段用空行拼接的 prompt 字符串。

    说明:
        大段正文不内联，引导子 agent 用 ``read_file`` 读 ``[context_refs]``/``[hot_files]``。
    """
    parts = [task.strip()]
    note = context.strip()
    if note:
        # Keep pasted context short; prefer path pointers for large material.
        parts.append(note[:2_000])
    refs = _normalize_refs(context_refs, paths)
    if refs:
        parts.append("[context_refs]\n" + "\n".join(f"- {path}" for path in refs))
    hot = _normalize_refs(hot_files)
    if hot:
        parts.append("[hot_files]\n" + "\n".join(f"- {path}" for path in hot))
    return "\n\n".join(part for part in parts if part)


async def execute_delegate(**kwargs: Any) -> dict[str, Any]:
    """Run a spawned child (never re-parks). Used by the controller join loop."""
    kwargs["wait"] = False
    return await run_delegate(**kwargs)


async def resume_parked_child(subagent_id: str, approval: Any) -> dict[str, Any]:
    """Continue one child that parked on approval. Missing state fails closed."""
    parked = _PARKED_CHILDREN.get(subagent_id)
    if not parked:
        return {
            "status": "failed",
            "error": "子代理已结束",
            "summary": "子代理已结束，请重试",
            "subagent_id": subagent_id,
            "origin": f"child/{subagent_id}",
        }
    engine = parked["engine"]
    state = parked["state"]
    depth = bump_delegate_depth()
    try:
        summary = await engine.resume_after_tool_approval(state, approval)
    finally:
        reset_delegate_depth(depth)
    if summary == "waiting_approval":
        pending = dict(getattr(engine, "pending_approval", None) or {})
        return {
            "status": "approval_required",
            "origin": f"child/{subagent_id}",
            "subagent_id": subagent_id,
            "summary": "子代理等待审批",
            "window_taint": str(pending.get("window_taint") or ""),
            "sink_class": str(pending.get("sink_class") or ""),
            "child_tool_name": pending.get("tool_name"),
            "child_tool_call_id": pending.get("tool_call_id"),
            "child_arguments": pending.get("arguments") or {},
            "approval_id": pending.get("approval_id"),
            "args_hash": pending.get("args_hash"),
            "policy_version": pending.get("policy_version"),
            "expires_at": pending.get("expires_at"),
        }
    _PARKED_CHILDREN.pop(subagent_id, None)
    writer = get_event_writer()
    text = (summary or "sub-agent completed").strip()
    if writer is not None:
        await writer(
            event_type="subagent.completed",
            payload={
                "subagent_id": subagent_id,
                "agent_type": str(getattr(state, "scenario_id", "") or ""),
                "summary": text[:500],
            },
        )
    taint = "external" if getattr(state, "saw_external", False) else str(
        getattr(state, "window_taint", "workspace") or "workspace"
    )
    return {
        "status": "completed" if not getattr(state, "cancelled", False) else "cancelled",
        "subagent_id": subagent_id,
        "summary": text[:500],
        "_taint": taint,
    }
