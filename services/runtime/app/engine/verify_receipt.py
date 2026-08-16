"""Wave 4 W9: verify receipt at Turn final edge (veto 13).

Classic trigger = code edit succeeded, no testish run after last edit.
Issue-repro trigger = repo tests went green but problem.md behavior not
exercised *successfully after the latest code edit*.
Never blocks cancel/failed; each kind at most once per Turn; omit when remaining < K.
"""

from __future__ import annotations

from typing import Any

from app.structural.issue_repro import (
    extract_issue_repro_hints,
    is_clearing_repro_result,
    is_green_test_result,
    load_problem_text,
    obligations_met_for_command,
)
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
        _ensure_issue_repro_hints(state)
        # Pre-edit issue repro no longer counts.
        state.issue_repro_satisfied = False
        state.issue_repro_edits_since = int(getattr(state, "issue_repro_edits_since", 0) or 0) + 1
        return

    if name == "run_tests":
        if result.get("status") == "rejected" or result.get("error") == "test_command_not_allowed":
            return
        state.verify_pending = False
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        _note_issue_repro_from_command(state, cmd, result)
        if cmd and result.get("status") not in {"passed", "executed"}:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)
        return

    if name == "run_command":
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        # Issue repro is often ``python -c`` (not testish) — still count it.
        if cmd:
            _note_issue_repro_from_command(state, cmd, result, allow_non_testish=True)
        if not is_testish_command(cmd):
            return
        state.verify_pending = False
        if result.get("status") not in {"executed", "passed"} or int(result.get("exit_code") or 1) != 0:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)
        _arm_issue_repro_if_needed(state, cmd, result)


def _ensure_issue_repro_hints(state: Any) -> None:
    if bool(getattr(state, "issue_repro_loaded", False)):
        return
    state.issue_repro_loaded = True
    try:
        from app.tools.core.paths import _workspace_root

        text = load_problem_text(_workspace_root())
    except Exception:
        text = ""
    hints = extract_issue_repro_hints(text)
    state.issue_repro_commands = list(hints.get("commands") or [])[:5]
    state.issue_repro_markers = list(hints.get("markers") or [])[:8]
    state.issue_repro_required_tokens = list(hints.get("required_tokens") or [])[:6]
    state.issue_repro_assets = list(hints.get("assets") or [])[:2]
    state.issue_repro_casefold_assets = list(hints.get("casefold_assets") or [])[:2]
    state.issue_repro_fail_signals = list(hints.get("fail_signals") or [])[:6]
    state.issue_repro_expect_signals = list(hints.get("expect_signals") or [])[:6]
    state.issue_repro_need_roundtrip = bool(hints.get("need_roundtrip"))
    state.issue_repro_need_casefold = bool(hints.get("need_casefold"))
    state.issue_repro_roundtrip_formats = list(hints.get("roundtrip_formats") or [])[:4]
    state.issue_repro_roundtrip_kwargs = list(hints.get("roundtrip_kwargs") or [])[:4]


def _issue_repro_hints_dict(state: Any) -> dict[str, Any]:
    return {
        "commands": list(getattr(state, "issue_repro_commands", None) or []),
        "markers": list(getattr(state, "issue_repro_markers", None) or []),
        "required_tokens": list(getattr(state, "issue_repro_required_tokens", None) or []),
        "assets": list(getattr(state, "issue_repro_assets", None) or []),
        "casefold_assets": list(getattr(state, "issue_repro_casefold_assets", None) or []),
        "fail_signals": list(getattr(state, "issue_repro_fail_signals", None) or []),
        "expect_signals": list(getattr(state, "issue_repro_expect_signals", None) or []),
        "need_roundtrip": bool(getattr(state, "issue_repro_need_roundtrip", False)),
        "need_casefold": bool(getattr(state, "issue_repro_need_casefold", False)),
        "roundtrip_formats": list(getattr(state, "issue_repro_roundtrip_formats", None) or []),
        "roundtrip_kwargs": list(getattr(state, "issue_repro_roundtrip_kwargs", None) or []),
    }


def _issue_repro_hints_present(state: Any) -> bool:
    return bool(
        list(getattr(state, "issue_repro_commands", None) or [])
        or list(getattr(state, "issue_repro_markers", None) or [])
        or list(getattr(state, "issue_repro_required_tokens", None) or [])
        or list(getattr(state, "issue_repro_assets", None) or [])
        or list(getattr(state, "issue_repro_fail_signals", None) or [])
        or bool(getattr(state, "issue_repro_need_roundtrip", False))
        or bool(getattr(state, "issue_repro_need_casefold", False))
    )


def _command_matches_state_issue_repro(state: Any, cmd: str) -> bool:
    return obligations_met_for_command(cmd, _issue_repro_hints_dict(state))


def _note_issue_repro_from_command(
    state: Any,
    cmd: str,
    result: dict[str, Any],
    *,
    allow_non_testish: bool = False,
) -> None:
    if not _issue_repro_hints_present(state):
        _ensure_issue_repro_hints(state)
    if not _issue_repro_hints_present(state):
        return
    if _command_matches_state_issue_repro(state, cmd):
        if is_clearing_repro_result(
            result,
            fail_signals=list(getattr(state, "issue_repro_fail_signals", None) or []),
            expect_signals=list(getattr(state, "issue_repro_expect_signals", None) or []),
        ):
            state.issue_repro_satisfied = True
            state.issue_repro_armed = False
            state.issue_repro_edits_since = 0
        # Matching but failed / still emitting issue failure → do not satisfy.
        return
    if not allow_non_testish or is_testish_command(cmd):
        _arm_issue_repro_if_needed(state, cmd, result)


def _arm_issue_repro_if_needed(state: Any, cmd: str, result: dict[str, Any]) -> None:
    if bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0:
        return
    if bool(getattr(state, "issue_repro_receipt_sent", False)):
        return
    if not _issue_repro_hints_present(state):
        return
    if _command_matches_state_issue_repro(state, cmd):
        return
    if not is_green_test_result(result):
        return
    # Green repo tests without a successful post-edit issue repro → arm gate.
    state.issue_repro_armed = True


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


def _remaining_steps(state: Any) -> int:
    return int(getattr(state, "max_steps", 0) or 0) - int(
        getattr(state, "step_count", 0) or 0
    )


def should_inject_verify_receipt(
    state: Any,
    *,
    reserve_steps: int = DEFAULT_VERIFY_RECEIPT_RESERVE_STEPS,
) -> bool:
    if bool(getattr(state, "cancelled", False)):
        return False
    if bool(getattr(state, "budget_exceeded", False)):
        return False
    if _remaining_steps(state) < max(1, int(reserve_steps)):
        return False

    if (
        bool(getattr(state, "verify_pending", False))
        and int(getattr(state, "code_edits_since_verify", 0) or 0) >= 1
        and not bool(getattr(state, "verify_receipt_sent", False))
    ):
        return True

    satisfied = bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0
    if (
        bool(getattr(state, "issue_repro_armed", False))
        and not satisfied
        and not bool(getattr(state, "issue_repro_receipt_sent", False))
        and _issue_repro_hints_present(state)
    ):
        return True
    return False


def verify_receipt_kind(state: Any) -> str:
    """Which receipt text/flags to use when injecting."""
    satisfied = bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0
    if (
        bool(getattr(state, "issue_repro_armed", False))
        and not satisfied
        and not bool(getattr(state, "issue_repro_receipt_sent", False))
        and not (
            bool(getattr(state, "verify_pending", False))
            and not bool(getattr(state, "verify_receipt_sent", False))
        )
    ):
        return "issue_repro"
    return "classic"


def mark_verify_receipt_injected(state: Any) -> str:
    kind = verify_receipt_kind(state)
    if kind == "issue_repro":
        state.issue_repro_receipt_sent = True
        state.issue_repro_armed = False
    else:
        state.verify_receipt_sent = True
    return kind


def build_verify_receipt_text(state: Any) -> str:
    if verify_receipt_kind(state) == "issue_repro":
        return _build_issue_repro_receipt_text(state)
    return _build_classic_receipt_text(state)


def _build_classic_receipt_text(state: Any) -> str:
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


def _build_issue_repro_receipt_text(state: Any) -> str:
    lines = [
        "verify_receipt: 仓库自带测试已绿，但编辑后尚未按问题描述完成行为验收",
        "  说明: 现有 test_*.py 全绿 / 编辑前复现 都不算；"
        "须在本轮代码编辑之后完成下列义务",
    ]
    if bool(getattr(state, "issue_repro_need_roundtrip", False)):
        fmts = list(getattr(state, "issue_repro_roundtrip_formats", None) or [])
        kws = list(getattr(state, "issue_repro_roundtrip_kwargs", None) or [])
        detail = []
        if fmts:
            detail.append(f"format={','.join(fmts[:3])}")
        if kws:
            detail.append(",".join(kws[:3]))
        lines.append(
            "  obligation_roundtrip: write → read 往返"
            + (f" ({'; '.join(detail)})" if detail else "")
            + "；只用 write 修掉 TypeError 不算"
        )
    if bool(getattr(state, "issue_repro_need_casefold", False)):
        lines.append(
            "  obligation_casefold: issue 主张大小写不敏感 — "
            "须对问题样例（或你已跑通的同格式内容）做非注释行 .lower() 后再读成功"
        )
    assets = list(getattr(state, "issue_repro_assets", None) or [])
    if assets:
        preview = assets[0] if len(assets[0]) <= 200 else assets[0][:200] + "\n..."
        lines.append("  issue_sample (write exactly, then run the API/command from the issue):")
        for pline in preview.splitlines() or [preview]:
            lines.append(f"    {pline}")
    cf_assets = list(getattr(state, "issue_repro_casefold_assets", None) or [])
    if cf_assets:
        preview = cf_assets[0] if len(cf_assets[0]) <= 160 else cf_assets[0][:160] + "\n..."
        lines.append("  casefold_sample:")
        for pline in preview.splitlines() or [preview]:
            lines.append(f"    {pline}")
    required = list(getattr(state, "issue_repro_required_tokens", None) or [])
    if required and not assets:
        lines.append(f"  required_tokens: {', '.join(required[:6])}")
    fails = list(getattr(state, "issue_repro_fail_signals", None) or [])
    if fails:
        lines.append(f"  must_not_still_show: {', '.join(fails[:4])}")
    expects = list(getattr(state, "issue_repro_expect_signals", None) or [])
    if expects and not fails:
        lines.append(f"  expect_hint: {', '.join(expects[:4])}")
    commands = list(getattr(state, "issue_repro_commands", None) or [])
    markers = list(getattr(state, "issue_repro_markers", None) or [])
    if commands:
        lines.append("  suggested_repro:")
        for cmd in commands[:_RELATED_CAP]:
            lines.append(f"    - {cmd}")
    elif markers and not assets:
        lines.append(f"  issue_markers: {', '.join(markers[:6])}")
        lines.append(
            "  suggested_repro: 用 run_command 按问题中的示例构造输入并复现"
        )
    lines.append(
        "  要求: 覆盖上述 obligation_* 并确认成功后再交卷；"
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
