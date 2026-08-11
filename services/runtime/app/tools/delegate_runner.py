from __future__ import annotations

import re
from dataclasses import replace
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

# Parent projection / meters must not absorb sub-agent side effects.
# Live UI events are forwarded with subagent_id stamped (nested readonly chat).
_SUPPRESSED_SUB_EVENTS = frozenset(
    {
        "section.draft.delta",
        "retrieval.completed",
        "patch.proposed",
        "outline.updated",
        "turn.plan",
        "cards.pinned",
        "context.reported",
        "usage.reported",
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
    # Nested workers run inside an already-scheduled delegate. Approvals belong to
    # the parent Turn; a subagent write_file gate would emit approval.requested but
    # leave parent pending_approval empty (summary "waiting_approval" collision).
    return [replace(spec, requires_approval=False) for spec in specs]


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
        await ctx.write_event(
            event_type=event_type, payload=stamped, step_index=step_index
        )

    depth_token = bump_delegate_depth()
    try:
        collab_board = ""
        if ctx.scenario_id == "collab":
            collab_board = (
                " For durable handoffs, write short findings under artifacts/collab/ "
                "when a later worker will need them. End with one line "
                "`ARTIFACT_REFS: path1, path2` (workspace-relative). "
                "Do not paste large file bodies into the summary."
            )
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

    if sub_state.cancelled:
        status = "cancelled"
        summary = summary or "sub-agent cancelled"
    elif summary == "waiting_approval":
        # Should not happen after approval waiver; keep parent Turn from hanging.
        status = "failed"
        summary = (
            "sub-agent hit an approval gate; nested writes must not require approval"
        )
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

    return {
        "subagent_id": subagent_id,
        "agent_type": agent_type,
        "summary": summary,
        "artifact_refs": artifact_refs,
        "status": status,
    }


def _extract_artifact_refs(text: str) -> list[str]:
    """Parse `ARTIFACT_REFS: a, b` lines from a sub-agent summary (handoff blackboard)."""
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
