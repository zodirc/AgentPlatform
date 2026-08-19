from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.engine.read_registry import PathReadState


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TurnState:
    turn_id: UUID
    session_id: UUID
    run_id: UUID
    trace_id: UUID
    scenario_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    max_steps: int = 40
    usage: Usage = field(default_factory=Usage)
    cancelled: bool = False
    cancel_force: bool = False
    termination_reason: str = "final"
    budget_exceeded: bool = False
    delivery: dict[str, Any] | None = None
    # Optional Intake hint (e.g. multi-goal → suggest update_plan). Never forces tools.
    plan_hint: str | None = None
    # docs/25 — planning | executing | None (normal Agent).
    plan_phase: str | None = None
    # docs/29 — ops_eval per-Turn model_mode survives approve/deny checkpoint resume.
    model_mode: str | None = None
    # Ops / official L1 StartTurn: unattended — auto-approve write/exec gated tools.
    ops_eval: bool = False
    # docs/30 WN3/AQ1 — cards/focus/plan phase; survives checkpoint resume (not welded into system).
    volatile_context: str = ""
    # After user approves one write-class tool this Turn, further sticky writes skip approval.
    writes_preapproved: bool = False
    # After user approves run_command this Turn, further run_command skips approval.
    exec_preapproved: bool = False
    # docs/34 RC1 — Turn-scoped read_file coverage (hard-gate read-after-complete).
    read_registry: dict[str, PathReadState] = field(default_factory=dict)
    # C1: paths whose full read body left the visible assemble window (fold/collapse/snip).
    # One re-read per path per Turn is allowed without tripping read_after_complete.
    evicted_paths: set[str] = field(default_factory=set)
    evicted_reread_used: set[str] = field(default_factory=set)
    # Wave 4 W9: verify receipt trackers (tool facts only; survive checkpoint).
    verify_pending: bool = False
    verify_receipt_sent: bool = False
    code_edits_since_verify: int = 0
    related_tests_union: list[dict[str, str]] = field(default_factory=list)
    last_repro_command: str = ""
    last_test_first_failure: str = ""
    # Issue-behavior repro (problem.md): after green repo tests, one more gate.
    issue_repro_loaded: bool = False
    issue_repro_commands: list[str] = field(default_factory=list)
    issue_repro_markers: list[str] = field(default_factory=list)
    issue_repro_required_tokens: list[str] = field(default_factory=list)
    issue_repro_assets: list[str] = field(default_factory=list)
    issue_repro_casefold_assets: list[str] = field(default_factory=list)
    issue_repro_fail_signals: list[str] = field(default_factory=list)
    issue_repro_expect_signals: list[str] = field(default_factory=list)
    issue_repro_need_roundtrip: bool = False
    issue_repro_need_casefold: bool = False
    issue_repro_roundtrip_formats: list[str] = field(default_factory=list)
    issue_repro_roundtrip_kwargs: list[str] = field(default_factory=list)
    issue_repro_armed: bool = False
    issue_repro_satisfied: bool = False
    issue_repro_receipt_sent: bool = False
    # Code edits since last successful issue repro (must be 0 to stay satisfied).
    issue_repro_edits_since: int = 0
    # This Turn's StartTurn user text (not later injected receipts). Writing tools
    # parse quota / TOC-only from here; empty on legacy checkpoints.
    turn_user_text: str = ""
    # Writing hinge receipt: 看见…立马…却/回头 (not chapter-debt). Checkpointed.
    hinge_pending: bool = False
    hinge_receipt_sent: bool = False
    # Opening-chapter 「N年前」+失踪/尸体 dump (not chapter-count). Checkpointed.
    lore_pending: bool = False
    lore_receipt_sent: bool = False
    # Opening-chapter 宗/派 before a standable place. Checkpointed.
    opening_pending: bool = False
    opening_receipt_sent: bool = False

ContentBlock = dict[str, Any]
MessageRole = Literal["user", "assistant", "tool"]


def user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def assistant_tool_use(tool_call_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tool_call_id,
                "name": tool_name,
                "input": arguments,
            }
        ],
    }


def assistant_tool_uses(tool_calls: list[dict[str, Any]], *, text: str = "") -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if text.strip():
        content.append({"type": "text", "text": text})
    content.extend(
        {
            "type": "tool_use",
            "id": call["id"],
            "name": call["name"],
            "input": call.get("input", {}),
        }
        for call in tool_calls
    )
    return {"role": "assistant", "content": content}


def tool_result_message(tool_call_id: str, result: str, is_error: bool = False) -> dict[str, Any]:
    return {
        "role": "tool",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result,
                "is_error": is_error,
            }
        ],
    }
