from __future__ import annotations

from typing import Any

from app.settings import settings
from app.tools.core.paths import _resolve_path, _workspace_root

async def stub_echo(message: str, **_kwargs: Any) -> dict[str, Any]:
    preview = message[:120]
    return {"summary": f"[stub] processed: {preview}", "echo": message}


def _make_cancel_checker(turn_id: object):
    from uuid import UUID

    from app.controller.turn_controller import _check_cancel_flag

    tid = turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id))

    async def check_cancel() -> tuple[bool, bool]:
        return await _check_cancel_flag(tid)

    return check_cancel


async def run_command(command: str, turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    from app.structural.pager_redirect import resolve_pager_window, try_parse_pager_command
    from app.structural.test_run_redirect import (
        extract_sweb_env_argv,
        extract_test_command_for_redirect,
        is_swe_env_install_command,
        swe_install_reject_payload,
    )
    from app.structural.test_summary import attach_test_summary_for_run_command
    from app.tenant_context import current_ops_eval
    from app.tools.core.shell import run_shell_command
    from app.tools.core.swe_solve_env import load_swe_instance_marker, maybe_run_swe_eval_argv

    pager = try_parse_pager_command(command)
    if pager is not None:
        target = _resolve_path(str(pager["path"]))
        if target.is_file():
            from app.tools.core.read_tools import read_file

            offset, limit = resolve_pager_window(
                path=target,
                offset=pager.get("offset"),
                limit=pager.get("limit"),
                from_end=pager.get("from_end"),
            )
            out = await read_file(str(pager["path"]), offset=offset, limit=limit)
            out["redirected_from"] = "run_command"
            out["command"] = command
            return out

    # SWE ops_eval: pytest / env probes → local sweb.eval; block pip in Work.
    root = _workspace_root()
    if bool(current_ops_eval()) and load_swe_instance_marker(root) is not None:
        if is_swe_env_install_command(command):
            probe = None
            try:
                from app.tools.core.swe_solve_env import probe_solve_env

                probe = probe_solve_env(work_root=root, use_cache=True)
            except Exception:
                probe = None
            return swe_install_reject_payload(command, probe=probe)
        redirected = extract_test_command_for_redirect(command)
        if redirected is not None:
            from app.tools.core.edit_tools import run_tests

            out = await run_tests(command=redirected, turn_id=turn_id, **_kwargs)
            out["redirected_from"] = "run_command"
            out["original_command"] = command
            if out.get("command") != command:
                # Keep model-visible command as what they typed; note redirect in summary.
                out["command"] = command
                prev = str(out.get("summary") or "").strip()
                note = f"redirected to run_tests / sweb.eval: {redirected}"
                out["summary"] = f"{note}\n{prev}" if prev else note
            return out
        env_argv = extract_sweb_env_argv(command)
        if env_argv is not None:
            swe_out = maybe_run_swe_eval_argv(
                work_root=root,
                argv=env_argv,
                display_command=command,
                timeout_s=float(settings.tool_default_timeout_seconds),
                ops_eval=True,
                skip_sync=True,
            )
            if swe_out is not None:
                swe_out["redirected_from"] = "run_command"
                swe_out["original_command"] = command
                prev = str(swe_out.get("summary") or "").strip()
                note = "redirected to sweb.eval (env probe / python -c)"
                swe_out["summary"] = f"{note}\n{prev}" if prev else note
                return swe_out

    if settings.run_command_mode == "simulate":
        out = {
            "status": "executed",
            "command": command,
            "stdout": f"[simulated] {command}",
            "exit_code": 0,
            "summary": f"Simulated: {command[:80]}",
        }
        return attach_test_summary_for_run_command(out, command=command)

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    result = await run_shell_command(
        command=command,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
        check_cancel=check_cancel,
    )
    # Channel ②: after successful command, budgeted mtime+size light scan (§3.2).
    try:
        if int(result.get("exit_code") or 1) == 0:
            from app.structural.workspace_index.watch import light_scan_after_command
            from app.tenant_context import current_owner_user_id, current_work_id

            owner = current_owner_user_id()
            scan = await light_scan_after_command(
                work_id=current_work_id(),
                owner_user_id=str(owner) if owner else None,
                work_root=root,
                budget_ms=200.0,
            )
            if scan.get("status") == "scan_pending":
                result = {**result, "ast_scan": "scan_pending"}
    except Exception:
        pass
    return attach_test_summary_for_run_command(result, command=command)
async def check_citation(citation_id: str, source_path: str, **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(source_path)
    if not target.exists():
        return {"citation_id": citation_id, "valid": False, "error": "source not found"}
    text = target.read_text(encoding="utf-8", errors="replace")
    valid = citation_id.replace("cite:", "") in source_path or citation_id in text
    return {
        "citation_id": citation_id,
        "source_path": source_path,
        "valid": valid,
        "summary": "citation valid" if valid else "citation not found in source",
    }
async def slow_tool(duration_ms: int = 5000, turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    import asyncio

    from app.controller.turn_controller import _check_cancel_flag

    steps = max(1, int(duration_ms) // 100)
    for _ in range(steps):
        if turn_id is not None and (await _check_cancel_flag(turn_id))[0]:
            return {"status": "cancelled", "summary": "cancelled during slow_tool"}
        await asyncio.sleep(0.1)
    return {"status": "completed", "summary": "slow_tool finished"}


async def delegate(
    task: str,
    agent_type: str = "explore",
    context: str = "",
    context_refs: list[str] | None = None,
    paths: list[str] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.tools.delegate_runner import run_delegate

    return await run_delegate(
        task=task,
        agent_type=agent_type,
        context=context,
        context_refs=context_refs,
        paths=paths,
        **_kwargs,
    )
