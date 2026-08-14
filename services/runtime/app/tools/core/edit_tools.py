from __future__ import annotations

from typing import Any

from app.settings import settings
from app.tools.core.lsp_tools import _lsp_infra_failed
from app.tools.core.misc_tools import _make_cancel_checker
from app.tools.core.patch_tools import _unified_patch_apply_precheck
from app.tools.core.paths import (
    _assert_not_seed_corpus,
    _normalized_workspace_rel,
    _resolve_path,
    _workspace_root,
)

async def write_file(path: str, content: str, **_kwargs: Any) -> dict[str, Any]:
    from app.privacy.secret_scan import gate_write_content

    _assert_not_seed_corpus(path)
    blocked = gate_write_content(content, path=path)
    if blocked is not None:
        return blocked
    target = _resolve_path(path)
    old_text = ""
    if target.is_file():
        try:
            old_text = target.read_text(encoding="utf-8", errors="replace")
            if len(old_text) > 32_000:
                old_text = old_text[:32_000] + "\n...[truncated]"
        except OSError:
            old_text = ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        notify_path_changed(
            path,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            work_root=_workspace_root(),
        )
    except Exception:
        pass
    out: dict[str, Any] = {
        "path": path,
        "old_text": old_text,
        "new_text": content,
        "bytes_written": len(content.encode()),
        "summary": f"Wrote {path}",
        "status": "written",
    }
    # C-4: when writing a unified patch file, surface applyability to the model.
    rel = _normalized_workspace_rel(path)
    if rel.endswith((".patch", ".diff")):
        check = _unified_patch_apply_precheck(content)
        if check:
            out.update(check)
            if check.get("applies") is False:
                err = check.get("apply_check_error") or "git apply --check failed"
                out["summary"] = f"Wrote {path} but patch does not apply: {err}"
    return out


async def rename_file(
    path: str,
    new_path: str,
    *,
    overwrite: bool = False,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Rename or move a workspace file (narrow op — not export / not rewrite)."""
    src_rel = _normalized_workspace_rel(path)
    dst_rel = _normalized_workspace_rel(new_path)
    if not src_rel or not dst_rel:
        return {"status": "error", "error": "path and new_path are required"}
    if src_rel == dst_rel:
        return {
            "status": "ok",
            "path": src_rel,
            "new_path": dst_rel,
            "summary": f"Already named {dst_rel}",
        }

    try:
        _assert_not_seed_corpus(src_rel)
        _assert_not_seed_corpus(dst_rel)
        src = _resolve_path(src_rel)
        dst = _resolve_path(dst_rel)
    except PermissionError as exc:
        return {"status": "error", "error": str(exc)}

    if not src.exists():
        return {"status": "error", "error": f"File not found: {src_rel}"}
    if not src.is_file():
        return {
            "status": "error",
            "error": f"Not a file (directories unsupported): {src_rel}",
        }
    if dst.exists() and not overwrite:
        return {
            "status": "error",
            "error": f"Destination exists: {dst_rel}; pass overwrite=true to replace",
        }
    if dst.exists() and overwrite and dst.is_dir():
        return {"status": "error", "error": f"Destination is a directory: {dst_rel}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and overwrite:
        dst.unlink()
    src.rename(dst)
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        oid = str(owner) if owner else None
        wid = current_work_id()
        root = _workspace_root()
        notify_path_changed(
            src_rel, work_id=wid, owner_user_id=oid, work_root=root, deleted=True
        )
        notify_path_changed(
            dst_rel, work_id=wid, owner_user_id=oid, work_root=root
        )
    except Exception:
        pass
    return {
        "status": "renamed",
        "path": src_rel,
        "new_path": dst_rel,
        "summary": f"Renamed {src_rel} → {dst_rel}",
    }


async def _impact_for_edit(
    *,
    path: str,
    old_text: str,
    new_text: str,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Impact stage: same find_references adapters; attached on successful code edits."""
    from app.structural.providers import language_for_path
    from app.structural.symbols import extract_symbols_from_edit

    if language_for_path(path) is None:
        return {
            "status": "skipped",
            "reason": "non_code_path",
            "symbol": None,
            "references": [],
            "lines": [],
        }

    symbols = extract_symbols_from_edit(old_text, new_text, limit=1)
    if not symbols:
        return {
            "status": "skipped",
            "reason": "no_symbol_detected",
            "symbol": None,
            "references": [],
            "lines": [],
        }

    symbol = symbols[0]
    from app.structural.adapters import find_references as _refs
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _refs(
        workspace,
        symbol,
        path=path,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=turn_id,
    )
    locations = list(out.get("locations") or [])
    pointers = list(out.get("pointers") or [])
    lines = format_locations_lines(locations)
    if pointers:
        lines = [*lines, *[f"# {p}" for p in pointers]]
    meta = dict(out.get("meta") or {})
    reason = str(meta.get("degraded_reason") or "")
    refs = [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations]
    if _lsp_infra_failed(reason):
        return {
            "status": "failed",
            "reason": reason,
            "symbol": symbol,
            "references": [],
            "lines": [],
            "pointers": [],
            "summary": (
                f"impact: language server required for references ({reason}); "
                "fix runtime provider"
            ),
            **meta,
        }
    return {
        "status": "ok",
        "symbol": symbol,
        "references": refs,
        "reference_count": len(refs),
        "lines": lines,
        "pointers": pointers,
        "summary": (
            f"impact: {len(refs)} reference(s) for {symbol!r}"
            if refs
            else f"impact: no references for {symbol!r}"
        ),
        **meta,
    }


async def _file_diagnostics_issues(
    path: str,
    *,
    turn_id: object | None = None,
    timeout_s: float | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Single-file LSP∪ruff diagnostics for edit_file.checks (never raises)."""
    import asyncio
    import shlex

    from app.structural.format import merge_issues, parse_ruff_concise_line
    from app.structural.types import Issue
    from app.tools.core.shell import run_shell_command

    workspace = _workspace_root().resolve()
    root = _resolve_path(path)
    try:
        rel = str(root.relative_to(workspace))
    except ValueError:
        rel = path
    budget = float(
        timeout_s
        if timeout_s is not None
        else getattr(settings, "structural_checks_timeout_s", settings.structural_diag_timeout_s)
    )
    meta: dict[str, Any] = {
        "provider": "ruff",
        "degraded_reason": None,
        "cold_start": False,
    }
    ruff_issues: list[Issue] = []
    try:
        result = await asyncio.wait_for(
            run_shell_command(
                command=f"python -m ruff check {shlex.quote(rel)} --output-format concise",
                cwd=workspace,
                timeout_s=min(budget, 120.0),
            ),
            timeout=budget + 1.0,
        )
        combined = "\n".join(
            part
            for part in (str(result.get("stdout") or ""), str(result.get("stderr") or ""))
            if part
        ).strip()
        for line in combined.splitlines():
            parsed = parse_ruff_concise_line(line, default_path=rel)
            if parsed is not None:
                ruff_issues.append(parsed)
    except asyncio.TimeoutError:
        meta["degraded_reason"] = "timeout_or_error:ruff"
        return [], meta
    except Exception as exc:  # noqa: BLE001
        meta["degraded_reason"] = f"ruff_error:{type(exc).__name__}"

    lsp_issues: list[Issue] = []
    try:
        from app.structural.adapters import get_diagnostics

        lsp_out = await asyncio.wait_for(
            get_diagnostics(
                workspace,
                root,
                timeout_s=budget,
                turn_id=turn_id,
            ),
            timeout=budget + 1.0,
        )
        lsp_issues = list(lsp_out.get("issues") or [])
        lsp_meta = lsp_out.get("meta") or {}
        meta["cold_start"] = bool(lsp_meta.get("cold_start"))
        if lsp_meta.get("provider"):
            meta["provider"] = f"lsp+ruff:{lsp_meta.get('provider')}"
        elif lsp_issues:
            meta["provider"] = "lsp+ruff"
        reason = str(lsp_meta.get("degraded_reason") or "")
        if reason:
            meta["degraded_reason"] = reason
    except asyncio.TimeoutError:
        meta["degraded_reason"] = "timeout_or_error:lsp"
    except Exception as exc:  # noqa: BLE001
        meta["degraded_reason"] = f"lsp_error:{type(exc).__name__}"

    return merge_issues(lsp_issues, ruff_issues), meta


def _issue_key(issue: Any) -> tuple[str, int, str]:
    code = getattr(issue, "code", None) or ""
    message = getattr(issue, "message", "") or ""
    path = (getattr(issue, "path", "") or "").replace("\\", "/")
    line = int(getattr(issue, "line", 0) or 0)
    normalized = (code or message).strip().lower()
    return (path, line, normalized)


async def _checks_for_edit(
    *,
    path: str,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Collect pre-write diagnostic baseline for edit_file.checks (Wave 2 W1)."""
    from app.structural.providers import language_for_path

    if language_for_path(path) is None:
        return {
            "status": "skipped",
            "syntax": "skipped",
            "new_issues": [],
            "baseline_count": 0,
            "lines": [],
            "reason": "non_code_path",
        }

    max_issues = int(getattr(settings, "structural_checks_max_issues", 20))
    timeout_s = float(
        getattr(settings, "structural_checks_timeout_s", settings.structural_diag_timeout_s)
    )
    baseline, _base_meta = await _file_diagnostics_issues(
        path, turn_id=turn_id, timeout_s=timeout_s
    )
    return {
        "_baseline": baseline,
        "_baseline_keys": {_issue_key(i) for i in baseline},
        "_max_issues": max_issues,
        "_timeout_s": timeout_s,
    }


async def _finalize_checks_after_write(
    *,
    path: str,
    pre: dict[str, Any],
    gate: Any,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """Diff post-write diagnostics against baseline; timeout never fails the edit."""
    from app.structural.format import format_diagnostics_lines

    if pre.get("status") == "skipped":
        return pre

    syntax_payload = gate.to_dict() if hasattr(gate, "to_dict") else {}
    syntax_status = getattr(gate, "status", None) or "ok"
    baseline = list(pre.get("_baseline") or [])
    baseline_keys = set(pre.get("_baseline_keys") or set())
    max_issues = int(pre.get("_max_issues") or 20)
    timeout_s = float(pre.get("_timeout_s") or settings.structural_diag_timeout_s)

    after, after_meta = await _file_diagnostics_issues(
        path, turn_id=turn_id, timeout_s=timeout_s
    )
    new_issues = [i for i in after if _issue_key(i) not in baseline_keys][:max_issues]
    reason = str(after_meta.get("degraded_reason") or "")
    if reason.startswith("timeout_or_error"):
        status = "timeout"
    elif _lsp_infra_failed(reason) and not new_issues and not after:
        status = "failed"
    else:
        status = "ok"

    lines = format_diagnostics_lines(new_issues, limit=max_issues)
    summary_bits = [f"checks.syntax={syntax_status}"]
    if new_issues:
        summary_bits.append(f"{len(new_issues)} new issue(s)")
    elif status == "ok":
        summary_bits.append("no new issues")
    else:
        summary_bits.append(status)
    return {
        "status": status,
        "syntax": syntax_status,
        "syntax_detail": syntax_payload,
        "new_issues": [i.to_dict() if hasattr(i, "to_dict") else i for i in new_issues],
        "baseline_count": len(baseline),
        "lines": lines,
        "summary": "; ".join(summary_bits),
        "provider": after_meta.get("provider"),
        "cold_start": after_meta.get("cold_start"),
        "degraded_reason": after_meta.get("degraded_reason"),
    }


async def edit_file(path: str, old_text: str, new_text: str, **_kwargs: Any) -> dict[str, Any]:
    from app.structural.span_match import (
        format_candidate_lines,
        nearest_span_candidates,
        occurrence_locations,
    )
    from app.structural.syntax import check_syntax_gate

    _assert_not_seed_corpus(path)
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    cand_limit = int(getattr(settings, "structural_span_candidates", 5))
    count = text.count(old_text)
    if count == 0:
        candidates = nearest_span_candidates(
            text, old_text, path=path, limit=cand_limit
        )
        lines = format_candidate_lines(candidates)
        return {
            "error": "old_text not found",
            "path": path,
            "applies": False,
            "candidates": candidates,
            "lines": lines,
            "summary": (
                f"old_text not found in {path}; "
                f"{len(candidates)} near candidate(s) — adjust span"
                if candidates
                else f"old_text not found in {path}"
            ),
        }
    if count > 1:
        candidates = occurrence_locations(
            text, old_text, path=path, limit=max(cand_limit, 20)
        )
        lines = format_candidate_lines(candidates)
        return {
            "error": f"old_text matches {count} times; use a longer unique span",
            "path": path,
            "applies": False,
            "match_count": count,
            "candidates": candidates,
            "lines": lines,
            "summary": f"old_text matches {count} times in {path}; pick one occurrence",
        }

    updated = text.replace(old_text, new_text, 1)
    turn_id = _kwargs.get("turn_id")

    # W1 syntax gate (pre-write): reject introduced parse errors; escape hatch if
    # the file was already broken.
    gate = check_syntax_gate(path, text, updated)
    if gate.blocked:
        line = gate.line or 1
        col = gate.col or 1
        msg = gate.message or "syntax error"
        lines = [
            f"{path}:{line}:{col} error [syntax] {msg}"
            + (f" | {gate.snippet}" if gate.snippet else "")
        ]
        return {
            "error": "syntax_error",
            "path": path,
            "applies": False,
            "status": "rejected",
            "checks": {
                "status": "rejected",
                "syntax": "error",
                "syntax_detail": gate.to_dict(),
                "new_issues": [],
                "baseline_count": 0,
                "lines": lines,
                "summary": f"syntax gate blocked edit at {path}:{line}",
            },
            "lines": lines,
            "summary": f"Rejected edit of {path}: introduced syntax error at line {line}",
        }

    # Baseline diagnostics on disk *before* write (incremental new_issues).
    pre_checks = await _checks_for_edit(path=path, turn_id=turn_id)

    target.write_text(updated, encoding="utf-8")
    try:
        from app.structural.workspace_index.dirty import notify_path_changed
        from app.tenant_context import current_owner_user_id, current_work_id

        owner = current_owner_user_id()
        notify_path_changed(
            path,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            work_root=_workspace_root(),
        )
    except Exception:
        pass
    impact = await _impact_for_edit(
        path=path,
        old_text=old_text,
        new_text=new_text,
        turn_id=turn_id,
    )
    checks = await _finalize_checks_after_write(
        path=path, pre=pre_checks, gate=gate, turn_id=turn_id
    )

    related_tests: list[str] = []
    try:
        import asyncio

        from app.structural.providers import language_for_path
        from app.structural.related_tests import related_tests_for_path

        if language_for_path(path) is not None:
            # Off event loop: even bounded scans must not starve cancel/health.
            related_tests = await asyncio.to_thread(
                related_tests_for_path, path, limit=5
            )
    except Exception:
        related_tests = []

    summary = f"Edited {path}"
    if impact.get("status") == "ok":
        summary = f"{summary}; {impact.get('summary') or 'impact attached'}"
    elif impact.get("status") == "failed":
        summary = f"{summary}; impact failed — {impact.get('reason') or 'lsp'}"
    if checks.get("status") == "ok" and checks.get("new_issues"):
        summary = f"{summary}; checks: {len(checks['new_issues'])} new issue(s)"
    elif checks.get("status") == "ok":
        summary = f"{summary}; checks: no new issues"
    elif checks.get("status") in {"timeout", "failed"}:
        summary = f"{summary}; checks {checks.get('status')}"
    elif checks.get("syntax") == "warning":
        summary = f"{summary}; checks: preexisting syntax warning"
    if related_tests:
        summary = f"{summary}; related_tests: {len(related_tests)} path(s)"

    out: dict[str, Any] = {
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "bytes_written": len(updated.encode("utf-8")),
        "summary": summary,
        "status": "edited",
        "applies": True,
        "impact": impact,
        "checks": checks,
    }
    if related_tests:
        out["related_tests"] = related_tests
        out["related_tests_count"] = len(related_tests)
    return out


async def run_tests(command: str = "pytest -q", turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    from app.tools.core.shell import run_argv_command
    from app.tools.core.test_command_gate import gate_run_tests_command

    # SB0: gate before simulate so malicious commands never look "passed".
    gated = gate_run_tests_command(command)
    if not gated.allowed:
        return {
            "command": command,
            "status": "rejected",
            "stdout": "",
            "stderr": gated.error or "test command not allowed",
            "exit_code": None,
            "summary": gated.error or "test command not allowed",
            "error": "test_command_not_allowed",
        }

    assert gated.argv is not None
    if settings.run_command_mode == "simulate":
        return {
            "command": command,
            "status": "passed",
            "stdout": "[simulated] 3 passed",
            "exit_code": 0,
            "summary": f"Simulated tests: {command}",
        }

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    root = _workspace_root()
    result = await run_argv_command(
        argv=gated.argv,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
        display_command=command,
        check_cancel=check_cancel,
    )
    exit_code = result.get("exit_code")
    passed = exit_code == 0 and result.get("status") == "executed"
    return {
        "command": command,
        "status": "passed" if passed else result.get("status", "failed"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "exit_code": exit_code,
        "summary": result.get("summary", f"Tests: {command}"),
        "sandbox": result.get("sandbox"),
    }
