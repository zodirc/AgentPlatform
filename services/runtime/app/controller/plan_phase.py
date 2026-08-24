"""Plan 模式相位辅助（docs/25）：planning / executing 的提示词纪律。

English: Plan mode phase helpers (docs/25) — planning vs executing tool/approval rules.

相位块作为 ``volatile_context`` 注入，不焊死进 system 前缀（WN3/AQ1）。
``system_prompt_for_phase`` 仅为旧布局兼容，新路径优先 ``plan_phase_block``。
"""

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
(`edit_file` / `write_file` / writing `propose_patch` / …) are pre-authorized for this checklist;
do not wait for per-edit consent. Follow the checklist step by step.
- When starting a step: call `update_plan` with that item `in_progress`.
- When finishing a step: call `update_plan` with that item `done` (or `completed`).
Replace the full items list each time. Never skip status updates.
"""


def normalize_plan_phase(raw: str | None) -> PlanPhase | None:
    """规范化外部传入的 plan_phase 字符串。

    参数:
        raw: 原始相位；可为 None 或任意大小写字符串。

    返回:
        ``\"planning\"`` / ``\"executing\"``；无法识别时为 None。
    """
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in {"planning", "executing"}:
        return value  # type: ignore[return-value]
    return None


def plan_phase_block(plan_phase: PlanPhase | None) -> str:
    """返回 Plan 相位指令块（volatile，不焊进 system 前缀）。

    参数:
        plan_phase: 已规范化相位；None 表示非 Plan 模式。

    返回:
        去首尾空白的指令文本；无相位时为空串。
    """
    if plan_phase == "planning":
        return _PLANNING_SYSTEM_SUFFIX.strip()
    if plan_phase == "executing":
        return _EXECUTING_SYSTEM_SUFFIX.strip()
    return ""


def system_prompt_for_phase(base: str, plan_phase: PlanPhase | None) -> str:
    """旧版：把相位块焊到 system 末尾。新代码应走 volatile_context（AQ1）。

    参数:
        base: 基础 system prompt。
        plan_phase: 相位。

    返回:
        拼接后的 system 文本；无相位时原样返回 base。
    """
    block = plan_phase_block(plan_phase)
    if not block:
        return base
    return f"{base.rstrip()}\n\n{block}\n"
