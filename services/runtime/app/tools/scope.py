"""场景工具裁剪。不导入具体 handler，避免写作宿主拉起全量工具聚合。"""

from __future__ import annotations

from dataclasses import replace

from app.scenarios.registry import ScenarioProfile
from app.tools.registry import ON_WRITE_TOOLS, ToolRegistry, ToolSpec

_LATE_STAGE_DROP = frozenset(
    {"search_sources", "delegate", "remember", "recall", "forget", "load_skill"}
)

PLANNING_TOOL_ALLOWLIST = frozenset({"update_plan"})
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_book_candidates"})
OUTLINE_WAIT_TOOL_ALLOWLIST = frozenset({"update_outline", "read_file"})
REVISION_PHASE_TOOL_ALLOWLIST = frozenset({"read_file", "grep", "glob"})
EDITOR_PHASE_TOOL_ALLOWLIST = frozenset(
    {"read_file", "grep", "glob", "editor_report"}
)
REREAD_PHASE_TOOL_ALLOWLIST = frozenset(
    {
        "read_file",
        "list_dir",
        "grep",
        "glob",
        "reread_book",
        "author_state",
        "propose_retcon",
    }
)
_PLAN_EXECUTING_WAIVE_APPROVAL = ON_WRITE_TOOLS | frozenset({"rename_file"})


def tool_scope(
    profile: ScenarioProfile,
    registry: ToolRegistry,
    *,
    plan_phase: str | None = None,
    opening_choice: bool = False,
    outline_wait: bool = False,
    editor_phase: bool = False,
    reread_phase: bool = False,
    revision_phase: bool = False,
) -> list[ToolSpec]:
    """按 Profile 与相位裁剪本回合工具。"""
    names = [name for name in profile.tool_names if name != "stub_echo"]
    phase = (plan_phase or "").strip().lower() or None
    if phase == "planning":
        names = [n for n in names if n in PLANNING_TOOL_ALLOWLIST]
        if "update_plan" not in names and registry.get("update_plan") is not None:
            names.append("update_plan")
    elif opening_choice:
        names = [n for n in names if n in OPENING_CHOICE_TOOL_ALLOWLIST]
        if (
            "propose_book_candidates" not in names
            and registry.get("propose_book_candidates") is not None
        ):
            names.append("propose_book_candidates")
    elif outline_wait:
        names = [n for n in names if n in OUTLINE_WAIT_TOOL_ALLOWLIST]
        if "update_outline" not in names and registry.get("update_outline") is not None:
            names.append("update_outline")
        if "read_file" not in names and registry.get("read_file") is not None:
            names.append("read_file")
    elif revision_phase:
        names = [n for n in names if n in REVISION_PHASE_TOOL_ALLOWLIST]
    elif editor_phase:
        names = [n for n in names if n in EDITOR_PHASE_TOOL_ALLOWLIST]
        if "editor_report" not in names and registry.get("editor_report") is not None:
            names.append("editor_report")
    elif reread_phase:
        names = [n for n in names if n in REREAD_PHASE_TOOL_ALLOWLIST]
        for extra in ("reread_book", "author_state", "propose_retcon"):
            if extra not in names and registry.get(extra) is not None:
                names.append(extra)
    specs: list[ToolSpec] = []
    for name in names:
        base = registry.get(name)
        if base is None:
            continue
        requires = base.requires_approval
        override = profile.approval_overrides.get(name)
        if override == "always":
            requires = True
        elif override == "never":
            requires = False
        elif override == "on_write":
            requires = name in ON_WRITE_TOOLS
        if phase == "executing" and name in _PLAN_EXECUTING_WAIVE_APPROVAL:
            requires = False
        specs.append(replace(base, requires_approval=requires))
    return specs


def late_stage_tools_disabled(
    *,
    step_count: int,
    max_steps: int,
    delivery: dict | None,
) -> bool:
    """成稿已交付或步数将尽时，闸掉检索与记忆类工具。"""
    delivery_ok = isinstance(delivery, dict) and str(delivery.get("delivery_status", "")) in {
        "ok",
        "warning",
    }
    remaining = max_steps - step_count
    late = step_count >= 8 and remaining <= 6
    return bool(delivery_ok or late)


def stage_tool_runtime_blocked(
    tool_name: str,
    *,
    step_count: int,
    max_steps: int,
    delivery: dict | None,
) -> bool:
    """晚期运行时拒绝检索/记忆工具，不改 tools[] 字节。"""
    if tool_name not in _LATE_STAGE_DROP:
        return False
    return late_stage_tools_disabled(
        step_count=step_count, max_steps=max_steps, delivery=delivery
    )


def stage_tool_scope(
    specs: list[ToolSpec],
    *,
    step_count: int,
    max_steps: int,
    delivery: dict | None,
) -> list[ToolSpec]:
    """遗留开关：晚期从 tools[] 物理删除检索类。默认关闭。"""
    from app.settings import settings

    if not bool(getattr(settings, "stage_tool_scope_mutate_schema", False)):
        return specs
    if not late_stage_tools_disabled(
        step_count=step_count, max_steps=max_steps, delivery=delivery
    ):
        return specs
    return [spec for spec in specs if spec.name not in _LATE_STAGE_DROP]
