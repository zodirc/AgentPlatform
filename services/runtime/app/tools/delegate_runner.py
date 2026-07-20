from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.controller.runtime_context import get_event_writer
from app.engine.agent_engine import AgentEngine
from app.engine.state import TurnState, user_message
from app.tools.bootstrap import build_registry
from app.tools.delegate_context import (
    bump_delegate_depth,
    current_delegate_depth,
    get_delegate_runtime,
    reset_delegate_depth,
)
from app.tools.registry import ToolSpec

MAX_DELEGATE_DEPTH = 2
DEFAULT_SUBAGENT_MAX_STEPS = 8

SUBAGENT_TOOL_NAMES: dict[str, list[str]] = {
    "researcher": ["read_file", "list_dir", "search_sources", "grep"],
    "drafter": ["read_file", "draft_section", "update_outline", "propose_patch"],
    "editor": ["read_file", "propose_patch", "edit_file", "write_file", "rename_file"],
    "fact_checker": ["read_file", "check_citation", "search_sources"],
    "stylist": ["read_file", "draft_section", "propose_patch"],
    "explore": ["read_file", "list_dir", "grep", "glob", "search_codebase", "search_sources"],
    "retrieve": ["read_file", "search_sources", "search_codebase", "list_dir"],
    "verify": ["read_file", "check_citation", "read_lints", "run_tests"],
    "edit": ["read_file", "propose_patch", "write_file", "edit_file", "rename_file"],
    "planner": ["read_file", "list_dir", "update_plan", "grep"],
    "shell": ["read_file", "grep", "run_command"],
}

# Writing keeps role specialists and also allows explore/retrieve/planner:
# models often default to explore; workspace + sources exploration is legitimate.
WRITING_DEFAULT_SUBAGENTS = frozenset(
    {
        "researcher",
        "drafter",
        "editor",
        "fact_checker",
        "stylist",
        "explore",
        "retrieve",
        "planner",
    }
)
AGENT_DEFAULT_SUBAGENTS = frozenset({"explore", "retrieve", "verify", "edit", "planner", "shell"})

_SUPPRESSED_SUB_EVENTS = frozenset(
    {
        "step.started",
        "step.completed",
        "turn.thinking",
        "turn.token",
        "tool.started",
        "tool.completed",
        "tool.delta",
        "section.draft.delta",
        "retrieval.completed",
        "patch.proposed",
        "outline.updated",
        "turn.plan",
    }
)


def _allowed_subagent_types(scenario_id: str, profile_types: list[str]) -> frozenset[str]:
    if profile_types:
        return frozenset(profile_types)
    if scenario_id == "writing":
        return WRITING_DEFAULT_SUBAGENTS
    return AGENT_DEFAULT_SUBAGENTS


def _resolve_sub_tools(parent_tools: list[ToolSpec], agent_type: str) -> list[ToolSpec]:
    by_name = {spec.name: spec for spec in parent_tools}
    specs = [by_name[name] for name in SUBAGENT_TOOL_NAMES.get(agent_type, []) if name in by_name]
    if specs:
        return specs
    registry = build_registry()
    return [
        spec
        for name in SUBAGENT_TOOL_NAMES.get(agent_type, [])
        if (spec := registry.get(name)) is not None
    ]


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
        await ctx.write_event(event_type=event_type, payload=payload, step_index=step_index)

    depth_token = bump_delegate_depth()
    try:
        engine = AgentEngine(
            gateway=ctx.gateway,
            tools=sub_tools,
            system_prompt=(
                f"You are a focused {agent_type} sub-agent. "
                "Complete the delegated task using tools; return a concise factual summary. "
                "Prefer read_file on [context_refs] / [hot_files] paths instead of inventing paths "
                "or pasting large file bodies yourself."
            ),
            write_event=sub_write_event,
            check_cancel=ctx.check_cancel,
        )
        summary = await engine.run(sub_state)
    finally:
        reset_delegate_depth(depth_token)

    if sub_state.cancelled:
        status = "cancelled"
        summary = summary or "sub-agent cancelled"
    else:
        status = "completed"
        summary = (summary or "sub-agent completed").strip()

    await writer(
        event_type="subagent.completed",
        payload={
            "subagent_id": subagent_id,
            "agent_type": agent_type,
            "summary": summary[:500],
        },
    )

    return {
        "subagent_id": subagent_id,
        "agent_type": agent_type,
        "summary": summary,
        "status": status,
    }


def _normalize_refs(*groups: list[str] | None) -> list[str]:
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
