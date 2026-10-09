"""TurnState 检查点编解码。不连接数据库，服务器与文件宿主共用。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID

from app.engine.read_registry import deserialize_read_registry, serialize_read_registry
from app.engine.state import TurnState

_SNAPSHOT_BUDGET = 200_000


def _snapshot_payload(raw: Any) -> dict[str, str]:
    """Keep rollback text inside the checkpoint, capped so one file cannot fill it."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    used = 0
    for key, value in raw.items():
        if isinstance(value, dict) and "b64" in value:
            text = "b64:" + str(value.get("b64") or "")
        else:
            text = str(value)
        if used + len(text) > _SNAPSHOT_BUDGET:
            break
        out[str(key)] = text
        used += len(text)
    return out


def _snapshot_load(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        text = str(value)
        if text.startswith("b64:"):
            out[str(key)] = {"b64": text[4:]}
        else:
            out[str(key)] = text
    return out


def serialize_state(state: TurnState) -> dict[str, Any]:
    return {
        "turn_id": str(state.turn_id),
        "session_id": str(state.session_id),
        "run_id": str(state.run_id),
        "trace_id": str(state.trace_id),
        "scenario_id": state.scenario_id,
        "messages": state.messages,
        "step_count": state.step_count,
        "max_steps": state.max_steps,
        "usage": asdict(state.usage),
        "cancelled": state.cancelled,
        "cancel_force": state.cancel_force,
        "cancelled_at_phase": state.cancelled_at_phase,
        "termination_reason": state.termination_reason,
        "budget_exceeded": state.budget_exceeded,
        "turn_token_budget": int(getattr(state, "turn_token_budget", 0) or 0),
        "max_input_tokens": int(getattr(state, "max_input_tokens", 0) or 0),
        "max_output_tokens": int(getattr(state, "max_output_tokens", 0) or 0),
        "fill_ratio_max": float(getattr(state, "fill_ratio_max", 0.0) or 0.0),
        "model_queue_wait_s": float(getattr(state, "model_queue_wait_s", 0.0) or 0.0),
        "pointerized_n": int(getattr(state, "pointerized_n", 0) or 0),
        "loaded_skill_names": [
            str(n).strip().lower()
            for n in (getattr(state, "loaded_skill_names", None) or [])
            if str(n).strip()
        ],
        "delivery": state.delivery,
        "plan_hint": state.plan_hint,
        "plan_phase": state.plan_phase,
        "model_mode": state.model_mode,
        "ops_eval": bool(state.ops_eval),
        "volatile_context": state.volatile_context or "",
        "writes_preapproved": bool(state.writes_preapproved),
        "exec_preapproved": bool(state.exec_preapproved),
        "saw_external": bool(getattr(state, "saw_external", False)),
        "window_taint": str(getattr(state, "window_taint", "user") or "user"),
        "last_external_tool": str(getattr(state, "last_external_tool", "") or ""),
        "pinned_policy_version": str(getattr(state, "pinned_policy_version", "") or ""),
        "s1_snapshots": _snapshot_payload(getattr(state, "s1_snapshots", None)),
        "read_registry": serialize_read_registry(state.read_registry),
        # C1: survive approve/deny checkpoint resume.
        "evicted_paths": sorted(state.evicted_paths),
        "evicted_reread_used": sorted(state.evicted_reread_used),
        "verify_pending": bool(state.verify_pending),
        "verify_receipt_sent": bool(state.verify_receipt_sent),
        "code_edits_since_verify": int(state.code_edits_since_verify or 0),
        "related_tests_union": list(state.related_tests_union or []),
        "last_repro_command": str(state.last_repro_command or ""),
        "last_test_first_failure": str(getattr(state, "last_test_first_failure", "") or ""),
        "issue_repro_loaded": bool(getattr(state, "issue_repro_loaded", False)),
        "issue_repro_commands": list(getattr(state, "issue_repro_commands", None) or []),
        "issue_repro_markers": list(getattr(state, "issue_repro_markers", None) or []),
        "issue_repro_required_tokens": list(
            getattr(state, "issue_repro_required_tokens", None) or []
        ),
        "issue_repro_assets": list(getattr(state, "issue_repro_assets", None) or []),
        "issue_repro_casefold_assets": list(
            getattr(state, "issue_repro_casefold_assets", None) or []
        ),
        "issue_repro_fail_signals": list(
            getattr(state, "issue_repro_fail_signals", None) or []
        ),
        "issue_repro_expect_signals": list(
            getattr(state, "issue_repro_expect_signals", None) or []
        ),
        "issue_repro_need_roundtrip": bool(
            getattr(state, "issue_repro_need_roundtrip", False)
        ),
        "issue_repro_need_casefold": bool(
            getattr(state, "issue_repro_need_casefold", False)
        ),
        "issue_repro_roundtrip_formats": list(
            getattr(state, "issue_repro_roundtrip_formats", None) or []
        ),
        "issue_repro_roundtrip_kwargs": list(
            getattr(state, "issue_repro_roundtrip_kwargs", None) or []
        ),
        "issue_repro_armed": bool(getattr(state, "issue_repro_armed", False)),
        "issue_repro_satisfied": bool(getattr(state, "issue_repro_satisfied", False)),
        "issue_repro_receipt_sent": bool(getattr(state, "issue_repro_receipt_sent", False)),
        "issue_repro_edits_since": int(getattr(state, "issue_repro_edits_since", 0) or 0),
        "turn_user_text": str(getattr(state, "turn_user_text", "") or ""),
        "hinge_pending": bool(getattr(state, "hinge_pending", False)),
        "hinge_receipt_sent": bool(getattr(state, "hinge_receipt_sent", False)),
        "lore_pending": bool(getattr(state, "lore_pending", False)),
        "lore_receipt_sent": bool(getattr(state, "lore_receipt_sent", False)),
        "opening_pending": bool(getattr(state, "opening_pending", False)),
        "opening_receipt_sent": bool(getattr(state, "opening_receipt_sent", False)),
        "staccato_pending": bool(getattr(state, "staccato_pending", False)),
        "staccato_receipt_sent": bool(getattr(state, "staccato_receipt_sent", False)),
    }


def deserialize_state(data: dict[str, Any]) -> TurnState:
    from app.engine.state import Usage

    usage = data.get("usage") or {}
    return TurnState(
        turn_id=UUID(data["turn_id"]),
        session_id=UUID(data["session_id"]),
        run_id=UUID(data["run_id"]),
        trace_id=UUID(data["trace_id"]),
        scenario_id=str(data["scenario_id"]),
        messages=list(data.get("messages") or []),
        step_count=int(data.get("step_count", 0)),
        max_steps=int(data.get("max_steps", 40)),
        usage=Usage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
            cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
        ),
        cancelled=bool(data.get("cancelled", False)),
        cancel_force=bool(data.get("cancel_force", False)),
        cancelled_at_phase=(
            str(data["cancelled_at_phase"]) if data.get("cancelled_at_phase") else None
        ),
        termination_reason=str(data.get("termination_reason", "final")),
        budget_exceeded=bool(data.get("budget_exceeded", False)),
        turn_token_budget=int(data.get("turn_token_budget", 0) or 0),
        max_input_tokens=int(data.get("max_input_tokens", 0) or 0),
        max_output_tokens=int(data.get("max_output_tokens", 0) or 0),
        fill_ratio_max=float(data.get("fill_ratio_max", 0.0) or 0.0),
        model_queue_wait_s=float(data.get("model_queue_wait_s", 0.0) or 0.0),
        pointerized_n=int(data.get("pointerized_n", 0) or 0),
        loaded_skill_names=[
            str(n).strip().lower()
            for n in (data.get("loaded_skill_names") or [])
            if str(n).strip()
        ],
        delivery=data.get("delivery") if isinstance(data.get("delivery"), dict) else None,
        plan_hint=str(data["plan_hint"]) if data.get("plan_hint") else None,
        plan_phase=str(data["plan_phase"]) if data.get("plan_phase") else None,
        model_mode=str(data["model_mode"]) if data.get("model_mode") else None,
        ops_eval=bool(data.get("ops_eval", False)),
        volatile_context=str(data.get("volatile_context") or ""),
        writes_preapproved=bool(data.get("writes_preapproved", False)),
        exec_preapproved=bool(data.get("exec_preapproved", False)),
        saw_external=bool(data.get("saw_external", False)),
        window_taint=str(data.get("window_taint") or "user"),
        last_external_tool=str(data.get("last_external_tool") or ""),
        pinned_policy_version=str(data.get("pinned_policy_version") or ""),
        s1_snapshots=_snapshot_load(data.get("s1_snapshots")),
        read_registry=deserialize_read_registry(data.get("read_registry")),
        evicted_paths={
            str(p) for p in (data.get("evicted_paths") or []) if str(p).strip()
        },
        evicted_reread_used={
            str(p) for p in (data.get("evicted_reread_used") or []) if str(p).strip()
        },
        verify_pending=bool(data.get("verify_pending", False)),
        verify_receipt_sent=bool(data.get("verify_receipt_sent", False)),
        code_edits_since_verify=int(data.get("code_edits_since_verify") or 0),
        related_tests_union=related_union(data.get("related_tests_union")),
        last_repro_command=str(data.get("last_repro_command") or ""),
        last_test_first_failure=str(data.get("last_test_first_failure") or ""),
        issue_repro_loaded=bool(data.get("issue_repro_loaded", False)),
        issue_repro_commands=[
            str(x) for x in (data.get("issue_repro_commands") or []) if str(x).strip()
        ],
        issue_repro_markers=[
            str(x) for x in (data.get("issue_repro_markers") or []) if str(x).strip()
        ],
        issue_repro_required_tokens=[
            str(x) for x in (data.get("issue_repro_required_tokens") or []) if str(x).strip()
        ],
        issue_repro_assets=[
            str(x) for x in (data.get("issue_repro_assets") or []) if str(x).strip()
        ],
        issue_repro_casefold_assets=[
            str(x) for x in (data.get("issue_repro_casefold_assets") or []) if str(x).strip()
        ],
        issue_repro_fail_signals=[
            str(x) for x in (data.get("issue_repro_fail_signals") or []) if str(x).strip()
        ],
        issue_repro_expect_signals=[
            str(x) for x in (data.get("issue_repro_expect_signals") or []) if str(x).strip()
        ],
        issue_repro_need_roundtrip=bool(data.get("issue_repro_need_roundtrip", False)),
        issue_repro_need_casefold=bool(data.get("issue_repro_need_casefold", False)),
        issue_repro_roundtrip_formats=[
            str(x) for x in (data.get("issue_repro_roundtrip_formats") or []) if str(x).strip()
        ],
        issue_repro_roundtrip_kwargs=[
            str(x) for x in (data.get("issue_repro_roundtrip_kwargs") or []) if str(x).strip()
        ],
        issue_repro_armed=bool(data.get("issue_repro_armed", False)),
        issue_repro_satisfied=bool(data.get("issue_repro_satisfied", False)),
        issue_repro_receipt_sent=bool(data.get("issue_repro_receipt_sent", False)),
        issue_repro_edits_since=int(data.get("issue_repro_edits_since") or 0),
        turn_user_text=str(data.get("turn_user_text") or ""),
        hinge_pending=bool(data.get("hinge_pending", False)),
        hinge_receipt_sent=bool(data.get("hinge_receipt_sent", False)),
        lore_pending=bool(data.get("lore_pending", False)),
        lore_receipt_sent=bool(data.get("lore_receipt_sent", False)),
        opening_pending=bool(data.get("opening_pending", False)),
        opening_receipt_sent=bool(data.get("opening_receipt_sent", False)),
        staccato_pending=bool(data.get("staccato_pending", False)),
        staccato_receipt_sent=bool(data.get("staccato_receipt_sent", False)),
    )


def related_union(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
            cmd = str(item.get("command") or "").strip()
            if path:
                out.append({"path": path, "command": cmd})
        elif isinstance(item, str) and item.strip():
            out.append({"path": item.strip(), "command": ""})
    return out


