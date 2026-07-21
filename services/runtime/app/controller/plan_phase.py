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
You are **executing** an approved plan. Follow the checklist step by step.
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


def system_prompt_for_phase(base: str, plan_phase: PlanPhase | None) -> str:
    if plan_phase == "planning":
        return f"{base.rstrip()}{_PLANNING_SYSTEM_SUFFIX}"
    if plan_phase == "executing":
        return f"{base.rstrip()}{_EXECUTING_SYSTEM_SUFFIX}"
    return base
