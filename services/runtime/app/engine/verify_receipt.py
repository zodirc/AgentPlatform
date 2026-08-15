"""Wave 4 W9: one-shot verify receipt at Turn final edge (veto 13).

Trigger = pure tool facts (code edit succeeded, no testish run after last edit).
Never blocks cancel/failed; at most once per Turn; omit when remaining steps < K.
"""

from __future__ import annotations

from typing import Any

from app.structural.related_tests import related_test_paths
from app.structural.test_summary import is_testish_command

# Reserve steps so receipt + test run can still finish before max_steps.
DEFAULT_VERIFY_RECEIPT_RESERVE_STEPS = 10
_RELATED_CAP = 5


def note_tool_result_for_verify(
    state: Any,
    *,
    tool_name: str,
    result: dict[str, Any],
    arguments: dict[str, Any] | None = None,
) -> None:
    """Update TurnState verify trackers from a completed tool result."""
    if not isinstance(result, dict):
        return
    name = str(tool_name or "")
    if name == "edit_file" and result.get("status") == "edited":
        impact = result.get("impact") if isinstance(result.get("impact"), dict) else {}
        checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
        # Non-code paths skip impact/checks — do not arm verify.
        if impact.get("reason") == "non_code_path" or (
            checks.get("status") == "skipped" and impact.get("status") == "skipped"
        ):
            return
        state.code_edits_since_verify = int(getattr(state, "code_edits_since_verify", 0) or 0) + 1
        state.verify_pending = True
        related = result.get("related_tests")
        if isinstance(related, list) and related:
            _merge_related(state, related)
        return

    if name == "run_tests":
        if result.get("status") == "rejected" or result.get("error") == "test_command_not_allowed":
            return
        state.verify_pending = False
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        if cmd and result.get("status") not in {"passed", "executed"}:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)
        return

    if name == "run_command":
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        if not is_testish_command(cmd):
            return
        state.verify_pending = False
        if result.get("status") not in {"executed", "passed"} or int(result.get("exit_code") or 1) != 0:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)


def _note_first_failure(state: Any, result: dict[str, Any]) -> None:
    from app.structural.test_summary import format_failure_feed

    feed = result.get("failure_feed")
    if isinstance(feed, str) and feed.strip():
        state.last_test_first_failure = feed.strip()[:400]
        return
    summary = result.get("test_summary")
    formatted = format_failure_feed(summary if isinstance(summary, dict) else None)
    if formatted:
        state.last_test_first_failure = formatted[:400]


def should_inject_verify_receipt(
    state: Any,
    *,
    reserve_steps: int = DEFAULT_VERIFY_RECEIPT_RESERVE_STEPS,
) -> bool:
    if bool(getattr(state, "verify_receipt_sent", False)):
        return False
    if bool(getattr(state, "cancelled", False)):
        return False
    if bool(getattr(state, "budget_exceeded", False)):
        return False
    if not bool(getattr(state, "verify_pending", False)):
        return False
    if int(getattr(state, "code_edits_since_verify", 0) or 0) < 1:
        return False
    remaining = int(getattr(state, "max_steps", 0) or 0) - int(
        getattr(state, "step_count", 0) or 0
    )
    if remaining < max(1, int(reserve_steps)):
        return False
    return True


def build_verify_receipt_text(state: Any) -> str:
    n = int(getattr(state, "code_edits_since_verify", 0) or 0)
    lines = [
        f"verify_receipt: 本 Turn 改动 {n} 个代码文件，最后一次编辑后未运行任何测试",
    ]
    related = list(getattr(state, "related_tests_union", None) or [])
    if related:
        lines.append("  related_tests:")
        for item in related[:_RELATED_CAP]:
            if isinstance(item, dict):
                path = str(item.get("path") or "")
                cmd = str(item.get("command") or "")
                if path and cmd:
                    lines.append(f"    - {path} | {cmd}")
                elif path:
                    lines.append(f"    - {path}")
            elif isinstance(item, str) and item.strip():
                lines.append(f"    - {item.strip()}")
    repro = str(getattr(state, "last_repro_command", "") or "").strip()
    if repro:
        lines.append(f"  repro: {repro}")
    fail = str(getattr(state, "last_test_first_failure", "") or "").strip()
    if fail:
        lines.append("  last_failure:")
        for fline in fail.splitlines():
            lines.append(f"    {fline}")
    lines.append(
        "  要求: 运行上述任一验证后再交卷；若有 last_failure 须针对该条修复并重跑同一测；"
        "确实无法运行则说明原因后交卷"
    )
    return "\n".join(lines)


def _merge_related(state: Any, related: list[Any]) -> None:
    existing = list(getattr(state, "related_tests_union", None) or [])
    seen = set(related_test_paths(existing))
    for item in related:
        if isinstance(item, dict):
            path = str(item.get("path") or "").replace("\\", "/").lstrip("./")
            if not path or path in seen:
                continue
            cmd = str(item.get("command") or "").strip()
            if not cmd:
                from app.structural.related_tests import pytest_command_for

                cmd = pytest_command_for(path)
            existing.append({"path": path, "command": cmd})
            seen.add(path)
        elif isinstance(item, str) and item.strip():
            path = item.replace("\\", "/").lstrip("./")
            if not path or path in seen:
                continue
            from app.structural.related_tests import pytest_command_for

            existing.append({"path": path, "command": pytest_command_for(path)})
            seen.add(path)
        if len(existing) >= _RELATED_CAP:
            break
    state.related_tests_union = existing[:_RELATED_CAP]
