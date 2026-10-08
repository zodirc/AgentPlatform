"""写作回合组装：工具裁剪、系统提示、volatile 与待发事件。

控制器开工路径调用 ``assemble_writing_turn``。审批续跑不重新组装提示，
只在需要重建工具表时调用 ``select_turn_tools``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.scope import tool_scope
from app.writing.plan_phase import plan_phase_block

_SEED_OFF = (
    "## Product seed corpus (disabled for this Work)\n"
    "Standing `sources/seed/**` is off. Do not search, cite, list, or "
    "`path_prefix` into seed. Use only user uploads under `sources/` "
    "(excluding seed) and writing cards."
)

_RECALL_LINE = (
    "[memory_hint] User may refer to prior notes — use the recall tool if relevant; "
    "do not invent memories and do not auto-inject long-term memory."
)


@dataclass(frozen=True)
class WritingTurnAssembly:
    """一回合交给引擎的写作组装结果。"""

    tools: list[Any]
    system_prompt: str
    volatile_context: str
    events: list[tuple[str, dict[str, Any]]]
    opening_choice: bool
    editor_phase: bool
    reread_phase: bool


def select_turn_tools(
    profile: Any,
    registry: Any,
    *,
    plan_phase: str | None,
    message: str,
) -> tuple[list[Any], bool, bool, bool]:
    """Plan 规划闸优先；否则开篇候选闸；再编辑 / 回读相位。

    参数:
        profile: 场景 Profile。
        registry: ``build_registry()`` 的注册表。
        plan_phase: 已规范化的计划相位。
        message: 用户消息。

    返回:
        ``(tools, opening_choice, editor_phase, reread_phase)``。
    """
    from app.writing.opening_ponds import should_gate_opening_choice
    from app.writing.reread import should_gate_editor_phase, should_gate_reread_phase
    from app.writing.revision import should_gate_revision_phase

    opening_choice = False
    editor_phase = False
    reread_phase = False
    outline_wait = False
    if (plan_phase or "").strip().lower() != "planning":
        opening_choice = should_gate_opening_choice(
            message or "",
            tool_names=list(profile.tool_names),
        )
        if not opening_choice:
            from app.writing.turn_phase import should_gate_outline_wait

            outline_wait = should_gate_outline_wait(message or "")
        if not opening_choice and not outline_wait:
            editor_phase = should_gate_revision_phase(message or "") or should_gate_editor_phase(
                message or ""
            )
            if not editor_phase:
                reread_phase = should_gate_reread_phase(message or "")
    tools = tool_scope(
        profile,
        registry,
        plan_phase=plan_phase,
        opening_choice=opening_choice,
        outline_wait=outline_wait,
        editor_phase=editor_phase,
        reread_phase=reread_phase,
        revision_phase=should_gate_revision_phase(message or ""),
    )
    return tools, opening_choice, editor_phase, reread_phase


def _append_block(volatile_context: str, block: str) -> str:
    if not block:
        return volatile_context
    if volatile_context.strip():
        return f"{volatile_context.rstrip()}\n\n{block}\n"
    return f"{block}\n"


def assemble_writing_turn(
    *,
    profile: Any,
    registry: Any,
    message: str,
    plan_phase: str | None,
    recall_hint: bool = False,
    seed_visible: bool = True,
) -> WritingTurnAssembly:
    """组装本回合的工具、提示与待发事件。

    调用方须已绑定作品租约。``seed_visible`` 为假时在 volatile 末尾注明产品语料关闭。
    事件只收集，不在此处写库。

    参数:
        profile: 场景 Profile（含系统提示与钩子名）。
        registry: 工具注册表。
        message: 用户消息。
        plan_phase: 已规范化的计划相位。
        recall_hint: 为真时附加记忆提示，不把长期记忆焊进系统提示。
        seed_visible: 作品是否允许产品语料。

    返回:
        ``WritingTurnAssembly``。
    """
    from app.scenarios.hooks import resolve as resolve_hook

    tools, opening_choice, editor_phase, reread_phase = select_turn_tools(
        profile,
        registry,
        plan_phase=plan_phase,
        message=message or "",
    )
    system_prompt = profile.system_prompt
    volatile_context = ""
    events: list[tuple[str, dict[str, Any]]] = []
    composer = resolve_hook(profile.hooks.get("system_prompt_composer"))
    if composer is not None:
        new_prompt, vol, hooked = composer(profile.system_prompt, message)
        if new_prompt is not None:
            system_prompt = new_prompt
        if vol:
            volatile_context = vol
        events.extend(hooked or [])
    else:
        vcomp = resolve_hook(profile.hooks.get("volatile_composer"))
        if vcomp is not None:
            _np, vol, hooked = vcomp(profile.system_prompt, message)
            if vol:
                volatile_context = vol
            events.extend(hooked or [])

    # Plan 相位留在 volatile，不焊进可缓存的系统前缀。
    volatile_context = _append_block(volatile_context, plan_phase_block(plan_phase))
    if opening_choice:
        from app.writing.opening_ponds import opening_choice_block

        volatile_context = _append_block(volatile_context, opening_choice_block())
    elif editor_phase:
        from app.writing.editor import editor_phase_block, format_observations_block
        from app.writing.revision import (
            build_revision_context,
            revision_phase_block,
            should_gate_revision_phase,
        )

        if should_gate_revision_phase(message or ""):
            system_prompt = revision_phase_block()
            volatile_context = build_revision_context(message or "")
        else:
            edit_block = editor_phase_block()
            system_prompt = edit_block or system_prompt
            volatile_context = format_observations_block() or ""
    elif reread_phase:
        from app.writing.reread import reread_phase_block

        volatile_context = _append_block(volatile_context, reread_phase_block())

    if not seed_visible:
        volatile_context = _append_block(volatile_context, _SEED_OFF)
    if recall_hint:
        volatile_context = _append_block(volatile_context, _RECALL_LINE)

    return WritingTurnAssembly(
        tools=tools,
        system_prompt=system_prompt,
        volatile_context=volatile_context,
        events=events,
        opening_choice=opening_choice,
        editor_phase=editor_phase,
        reread_phase=reread_phase,
    )
