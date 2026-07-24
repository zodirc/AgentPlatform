"""Plan-mode phase helpers (docs/25): prompt discipline for planning/executing."""

from __future__ import annotations

from typing import Literal

PlanPhase = Literal["planning", "executing"]

_PLANNING_SYSTEM_SUFFIX = """

## Plan phase (platform · planning)
You are in **planning** phase only.
1. Call `update_plan` once with clear steps — every item MUST be `status=pending`.
2. Briefly tell the user the checklist is ready and wait for confirmation.
3. Do **not** start any step. Do **not** call other tools (search/read/write/exec are unavailable).
4. Do **not** mark items in_progress or done — the user must click「按此执行」first.
"""

_EXECUTING_SYSTEM_SUFFIX = """

## Plan phase (platform · executing)
You are **executing** an approved plan. The user already clicked「按此执行」— file edits
(`edit_file` / `propose_patch` / `write_file` / …) are pre-authorized for this checklist;
do not wait for per-edit consent. Follow the checklist step by step.
- When starting a step: call `update_plan` with that item `in_progress`.
- When finishing a step: call `update_plan` with that item `done` (or `completed`).
Replace the full items list each time. Never skip status updates.
"""


def normalize_plan_phase(raw: str | None) -> PlanPhase | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in {"planning", "executing"}:
        return value  # type: ignore[return-value]
    return None


def plan_phase_block(plan_phase: PlanPhase | None) -> str:
    """Return Plan-phase instructions as a volatile block (WN3/AQ1 — not welded into system)."""
    if plan_phase == "planning":
        return _PLANNING_SYSTEM_SUFFIX.strip()
    if plan_phase == "executing":
        return _EXECUTING_SYSTEM_SUFFIX.strip()
    return ""


def system_prompt_for_phase(base: str, plan_phase: PlanPhase | None) -> str:
    """Legacy welded layout. Prefer ``plan_phase_block`` + volatile_context (AQ1)."""
    block = plan_phase_block(plan_phase)
    if not block:
        return base
    return f"{base.rstrip()}\n\n{block}\n"
