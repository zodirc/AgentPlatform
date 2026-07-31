"""Collab harness hints — volatile only; does not change AgentEngine control flow."""

from __future__ import annotations

import json
import re
from typing import Any

COLLAB_GAP_MARK = "[collab_gap]"

_EDIT_TYPES = frozenset({"edit", "editor", "drafter"})
_CHECK_TYPES = frozenset({"verify", "shell"})


def collab_orchestrator_block() -> str:
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
    """Return (saw_edit_delegate, saw_verify_or_shell) from tool results this Turn."""
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
    """Refresh mid-Turn gap hint without rewriting the rest of volatile_context."""
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
    """Soft handoff hint for verify/shell when parent omitted context_refs."""
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
