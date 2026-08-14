from __future__ import annotations

from typing import Any

from app.settings import settings
from app.tools.core.paths import _resolve_path, _workspace_root

def _lsp_infra_failed(reason: str) -> bool:
    """True when the language server itself is missing/broken (not a symbol miss)."""
    r = (reason or "").strip()
    if not r:
        return False
    if r in {"lsp_unavailable", "no_provider", "server_unhealthy_backoff"}:
        return True
    return r.startswith("timeout_or_error") or r.startswith("start_failed")


async def read_lints(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    import shlex

    from app.structural.format import (
        format_diagnostics_lines,
        merge_issues,
        parse_ruff_concise_line,
    )
    from app.structural.types import Issue
    from app.tools.core.shell import run_shell_command

    root = _resolve_path(path)
    workspace = _workspace_root().resolve()
    try:
        rel = "." if path in {".", ""} else str(root.relative_to(workspace))
    except ValueError:
        rel = path

    ruff_issues: list[Issue] = []
    ruff_status: str | None = None
    result = await run_shell_command(
        command=f"python -m ruff check {shlex.quote(rel)} --output-format concise",
        cwd=workspace,
        timeout_s=min(settings.tool_default_timeout_seconds, 120.0),
    )
    ruff_status = str(result.get("status") or "")
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    for line in combined.splitlines():
        parsed = parse_ruff_concise_line(line, default_path=rel)
        if parsed is not None:
            ruff_issues.append(parsed)

    lsp_issues: list[Issue] = []
    meta: dict[str, Any] = {
        "provider": "ruff",
        "cold_start": False,
        "truncated": False,
        "unsupported": False,
        "degraded_reason": None,
    }
    if ruff_status not in {"timeout", "cancelled"}:
        try:
            from app.structural.adapters import get_diagnostics

            lsp_out = await get_diagnostics(
                workspace,
                root,
                timeout_s=float(settings.structural_diag_timeout_s),
                turn_id=_kwargs.get("turn_id"),
            )
            lsp_issues = list(lsp_out.get("issues") or [])
            lsp_meta = lsp_out.get("meta") or {}
            meta["cold_start"] = bool(lsp_meta.get("cold_start"))
            meta["truncated"] = bool(lsp_meta.get("truncated"))
            meta["unsupported"] = bool(lsp_meta.get("unsupported"))
            if lsp_meta.get("degraded_reason"):
                meta["degraded_reason"] = lsp_meta.get("degraded_reason")
            if lsp_meta.get("provider"):
                meta["provider"] = f"lsp+ruff:{lsp_meta.get('provider')}"
            elif lsp_issues:
                meta["provider"] = "lsp+ruff"
            reason = str(lsp_meta.get("degraded_reason") or "")
            if _lsp_infra_failed(reason) and not meta.get("unsupported"):
                return {
                    "path": path,
                    "issues": [],
                    "issue_count": 0,
                    "summary": (
                        f"read_lints: language server required but unavailable ({reason or 'unknown'}); "
                        "fix runtime image / provider"
                    ),
                    "status": "failed",
                    "lines": [],
                    **meta,
                }
        except Exception as exc:
            return {
                "path": path,
                "issues": [],
                "issue_count": 0,
                "summary": (
                    f"read_lints: language server failed ({type(exc).__name__}: {exc})"
                ),
                "status": "failed",
                "lines": [],
                "provider": "lsp_error",
                "cold_start": False,
                "truncated": False,
                "unsupported": False,
                "degraded_reason": f"lsp_error:{type(exc).__name__}",
            }

    if ruff_status in {"timeout", "cancelled"} and not lsp_issues:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": str(result.get("summary", "read_lints interrupted")),
            "status": ruff_status,
            "lines": [],
            **meta,
        }

    # Clean ruff run with no issues (and no LSP hits).
    if ruff_status == "executed" and not ruff_issues and not lsp_issues:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": f"read_lints: {rel} — no issues",
            "lines": [],
            **meta,
        }

    # ruff unavailable / empty failed run — list files when LSP also empty
    if not ruff_issues and not lsp_issues:
        if root.is_file():
            files = [root]
        elif root.is_dir():
            import asyncio
            from itertools import islice

            def _list_py(limit: int = 20) -> list:
                # Early-stop: do not materialize a full-tree list then slice.
                return list(islice((p for p in root.rglob("*.py") if p.is_file()), limit))

            files = await asyncio.to_thread(_list_py)
        else:
            return {
                "path": path,
                "issues": [],
                "issue_count": 0,
                "summary": "No lint targets",
                "lines": [],
                **meta,
            }
        listed = [
            Issue(
                path=str(fp.relative_to(workspace)),
                line=1,
                col=1,
                severity="info",
                message="ruff unavailable; file listed only",
                provider="ruff",
                sources=("ruff",),
            )
            for fp in files
        ]
        lines = format_diagnostics_lines(listed)
        return {
            "path": path,
            "issues": [i.to_dict() for i in listed],
            "issue_count": 0,
            "summary": f"read_lints: {len(files)} file(s); install ruff for diagnostics",
            "lines": lines,
            **meta,
        }

    merged = merge_issues(lsp_issues, ruff_issues)
    lines = format_diagnostics_lines(merged)
    summary = (
        f"read_lints: {rel} — no issues"
        if not merged
        else f"read_lints: {len(merged)} issue(s) in {rel}"
    )
    return {
        "path": path,
        "issues": [i.to_dict() for i in merged],
        "issue_count": len(merged),
        "summary": summary,
        "lines": lines,
        **meta,
    }


async def goto_definition(
    symbol: str,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Symbol-first definition lookup via LSP (agent structural lane)."""
    from app.structural.adapters import goto_definition as _goto
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _goto(
        workspace,
        symbol,
        path=path,
        line=line,
        col=col,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    lines = format_locations_lines(locations)
    meta = out.get("meta") or {}
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        return {
            "symbol": symbol,
            "locations": [],
            "lines": [],
            "summary": (
                f"goto_definition: language server required but failed ({reason}); "
                "fix runtime provider"
            ),
            "status": "failed",
            **meta,
        }
    summary = out.get("summary") or (
        f"goto_definition: {len(locations)} location(s) for {symbol!r}"
        if locations
        else f"goto_definition: no definition for {symbol!r}"
    )
    return {
        "symbol": symbol,
        "locations": [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations],
        "lines": lines,
        "suggest": out.get("suggest"),
        "summary": summary,
        **meta,
    }


async def find_references(
    symbol: str,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Symbol-first references via LSP (agent structural lane)."""
    from app.structural.adapters import find_references as _refs
    from app.structural.format import format_locations_lines

    workspace = _workspace_root().resolve()
    out = await _refs(
        workspace,
        symbol,
        path=path,
        line=line,
        col=col,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    pointers = list(out.get("pointers") or [])
    lines = format_locations_lines(locations)
    if pointers:
        lines = [*lines, *[f"# {p}" for p in pointers]]
    meta = out.get("meta") or {}
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        return {
            "symbol": symbol,
            "locations": [],
            "lines": [],
            "pointers": [],
            "summary": (
                f"find_references: language server required but failed ({reason}); "
                "fix runtime provider"
            ),
            "status": "failed",
            **meta,
        }
    summary = out.get("summary") or (
        f"find_references: {len(locations)} hit(s) for {symbol!r}"
        if locations
        else f"find_references: no references for {symbol!r}"
    )
    return {
        "symbol": symbol,
        "locations": [loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations],
        "lines": lines,
        "pointers": pointers,
        "suggest": out.get("suggest"),
        "summary": summary,
        **meta,
    }
