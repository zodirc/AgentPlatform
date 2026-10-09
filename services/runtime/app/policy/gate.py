"""ToolExecutor authorization. Structural decision first, detector second."""

from __future__ import annotations

from typing import Any

from app.policy.approval import POLICY_VERSION
from app.policy.matrix import decide, eval_command_allowed, local_tighten
from app.policy.snapshot import path_escapes, take_snapshot
from app.policy.taint import effective_window


def _blocked(
    *,
    status: str,
    tool_name: str,
    tool_call_id: str,
    reason: str,
    sink_class: str,
    window_taint: str,
    state: Any,
) -> dict[str, Any]:
    if status == "deny":
        return {
            "status": "error",
            "error": reason,
            "tool_name": tool_name,
            "summary": reason,
            "sink_class": sink_class,
            "window_taint": window_taint,
            "policy_version": POLICY_VERSION,
        }
    return {
        "status": "approval_required",
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "summary": reason,
        "sink_class": sink_class,
        "window_taint": window_taint,
        "policy_version": POLICY_VERSION,
        "external_source": str(getattr(state, "last_external_tool", "") or ""),
    }


async def authorize(
    *,
    spec: Any,
    state: Any,
    tool_name: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    granted: bool,
) -> dict[str, Any] | None:
    """Return a terminal result, or None when the handler may run.

    Specs with an empty sink_class keep the boolean approval flag so existing
    unit tests that build ad-hoc tools still parse. Production registration
    always fills the class.
    """
    from app.tools.delegate_context import current_delegate_depth

    window = effective_window(state)
    sink = str(getattr(spec, "sink_class", "") or "")

    from app.policy.scenario_policy import scenario_path_allowed

    if path_escapes(arguments) or not scenario_path_allowed(
        str(getattr(state, "scenario_id", "") or ""),
        arguments,
    ):
        return _child_or(
            _blocked(
                status="deny",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                reason="path escapes the work root",
                sink_class="S5",
                window_taint=window,
                state=state,
            ),
            depth=current_delegate_depth(),
        )

    from app.policy.matrix import tool_emergency_denied

    if tool_emergency_denied(tool_name):
        return _blocked(
            status="deny",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason="emergency denylist",
            sink_class="S5",
            window_taint=window,
            state=state,
        )

    if not sink:
        return await _legacy(
            spec=spec,
            state=state,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            arguments=arguments,
            granted=granted,
            window=window,
        )

    http_decision = None
    if tool_name == "http_fetch":
        from app.policy.egress import classify_http

        http_decision = classify_http(arguments, window_taint=window, state=state)
        if http_decision == "deny":
            sink = "S5"

    if sink == "S5" or (tool_name == "http_fetch" and http_decision == "deny"):
        return _blocked(
            status="deny",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason="destination blocked",
            sink_class="S5",
            window_taint=window,
            state=state,
        )

    from app.tools.core.sandbox import work_disk_exceeded

    if sink in {"S1", "S2"} and work_disk_exceeded():
        return _blocked(
            status="deny",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason="work disk quota exceeded",
            sink_class="S5",
            window_taint=window,
            state=state,
        )

    snapshot_ok = True
    if sink == "S1":
        snapshot_ok = take_snapshot(state, arguments)

    allowlisted = False
    eval_command = False
    if sink == "S2":
        from app.tools.command_allowlist import command_is_allowlisted

        # run_tests is the product's test runner, not a model-composed shell line.
        from app.policy.scenario_policy import scenario_command_allowed

        command = str(arguments.get("command") or "")
        allowlisted = (
            tool_name == "run_tests"
            or await command_is_allowlisted(state, arguments)
            or scenario_command_allowed(
                str(getattr(state, "scenario_id", "") or ""),
                command,
            )
        )
        eval_command = bool(getattr(state, "ops_eval", False)) and eval_command_allowed(command)

    ready = False
    if sink == "S2":
        from app.policy.plane import sandbox_is_ready

        ready = sandbox_is_ready()

    decision, reason = decide(
        tool_name=tool_name,
        sink_class=sink if http_decision != "deny" else "S5",
        window_taint=window,
        sandbox_ready=ready,
        command_allowlisted=allowlisted,
        eval_command=eval_command,
        snapshot_ok=snapshot_ok,
        http_decision=http_decision,
    )
    from app.policy.matrix import command_emergency_denied

    if sink == "S2" and command_emergency_denied(str(arguments.get("command") or "")):
        decision, reason = "deny", "emergency denylist"
    local = local_tighten(arguments)
    if local == "deny":
        decision, reason = "deny", "local rule"
    elif local == "require_approval" and decision == "allow":
        decision, reason = "require_approval", "local rule"
    from app.policy.scenario_policy import apply_overlay

    overlaid = apply_overlay(
        decision,
        sink=sink if http_decision != "deny" else "S5",
        scenario_id=str(getattr(state, "scenario_id", "") or ""),
        tool_name=tool_name,
        window_taint=window,
    )
    if overlaid != decision:
        decision, reason = overlaid, "scenario policy"

    if sink in {"S3", "S4"} and decision in {"allow", "require_approval"}:
        from app.policy.detector import check_deviation, injection_mode, tighten
        from app.policy.taint import raise_window

        signal = await check_deviation(
            str(getattr(state, "turn_user_text", "") or ""),
            arguments,
        )
        if signal == "unavailable":
            raise_window(state, "external")
        from app.policy.scenario_policy import scenario_detector_mode

        mode = scenario_detector_mode(str(getattr(state, "scenario_id", "") or "")) or injection_mode()
        tightened = tighten(decision, signal, mode=mode)
        if tightened != decision:
            decision = tightened
            reason = "detector tightened"

    if decision == "allow" or (decision == "require_approval" and granted):
        return None
    blocked = _blocked(
        status="deny" if decision == "deny" else "approval_required",
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        reason=reason,
        sink_class=sink,
        window_taint=window,
        state=state,
    )
    return _child_or(blocked, depth=current_delegate_depth())


def _child_or(blocked: dict[str, Any], *, depth: int) -> dict[str, Any]:
    """Bubble a child approval to the parent turn. A deny stays a deny.

    The parent parks with origin ``child/<id>`` and resumes that child after
    the user decides. Legacy specs without a sink class still return
    「需要父代理执行」 from ``_legacy``.
    """
    if depth <= 0 or blocked.get("status") == "error":
        return blocked
    bubbled = dict(blocked)
    bubbled["origin"] = "child"
    return bubbled


async def _legacy(
    *,
    spec: Any,
    state: Any,
    tool_name: str,
    tool_call_id: str,
    arguments: dict[str, Any],
    granted: bool,
    window: str,
) -> dict[str, Any] | None:
    """Boolean approval flag for specs that never went through the registry."""
    from app.tools.delegate_context import current_delegate_depth

    memory_tainted = tool_name == "remember" and window == "external"
    needs_gate = bool(getattr(spec, "requires_approval", False) or memory_tainted)
    if not needs_gate or granted:
        return None
    allowlisted = False
    if tool_name == "run_command":
        from app.tools.command_allowlist import command_is_allowlisted

        allowlisted = await command_is_allowlisted(state, arguments)
    if allowlisted:
        return None
    if current_delegate_depth() > 0:
        return {
            "status": "error",
            "error": "需要父代理执行",
            "tool_name": tool_name,
            "summary": "需要父代理执行",
        }
    return _blocked(
        status="approval_required",
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        reason="approval required",
        sink_class="",
        window_taint=window,
        state=state,
    )
