from __future__ import annotations

import asyncio
from typing import Any

from app.settings import settings
from app.tools.core.lsp_tools import _lsp_infra_failed
from app.tools.core.paths import _resolve_path, _workspace_root
from app.tools.core.read_tools import _lexical_scan_sync

async def _lexical_codebase_hits(
    query: str, path: str = ".", limit: int = 20, **_kwargs: Any
) -> dict[str, Any]:
    """Substring scan (escaped). Used as Locate fallback or non-symbol mode.

    Runs off the event loop — full-tree scans must not block asyncpg writers.
    """
    root = _resolve_path(path)
    if not root.exists():
        return {"hits": [], "error": f"Path not found: {path}"}
    scanned = await asyncio.to_thread(
        _lexical_scan_sync,
        root=root,
        workspace=_workspace_root(),
        pattern=query,
        escape=True,
        limit=limit,
    )
    if scanned.get("error"):
        return {"hits": [], "error": str(scanned["error"]), "match_count": 0}
    hits = list(scanned.get("matches") or [])
    truncated = bool(scanned.get("truncated"))
    summary = f"search_codebase (lexical): {len(hits)} hit(s) for {query!r}"
    if truncated:
        summary += " (scan budget hit — results may be partial)"
    return {
        "hits": hits,
        "match_count": len(hits),
        "truncated": truncated,
        "files_scanned": int(scanned.get("files_scanned") or 0),
        "summary": summary,
    }


async def search_codebase(query: str, path: str = ".", limit: int = 20, **_kwargs: Any) -> dict[str, Any]:
    """Locate entry: symbol queries must resolve via goto_definition adapters."""
    from app.structural.symbols import is_symbol_query

    q = (query or "").strip()
    if not is_symbol_query(q):
        lexical = await _lexical_codebase_hits(q, path=path, limit=limit, **_kwargs)
        hits = list(lexical.get("hits") or [])
        return {
            "query": q,
            "mode": "lexical",
            "definitions": [],
            "hits": hits,
            "match_count": len(hits),
            "locate_incomplete": False,
            "truncated": bool(lexical.get("truncated")),
            "files_scanned": int(lexical.get("files_scanned") or 0),
            "summary": lexical.get("error")
            or lexical.get("summary")
            or f"search_codebase (lexical): {len(hits)} hit(s) for {q!r}",
            **({"error": lexical["error"]} if lexical.get("error") else {}),
        }

    from app.structural.adapters import goto_definition as _goto
    from app.structural.format import format_locations_lines
    from app.tenant_context import current_owner_user_id, current_work_id

    workspace = _workspace_root().resolve()

    # AST index coarse filter → LSP confirm (docs/core/tools-and-context.md §2 Locate).
    try:
        from app.structural.workspace_index.locate import locate_via_ast_index

        owner = current_owner_user_id()
        ast_out = await locate_via_ast_index(
            workspace=workspace,
            symbol=q,
            work_id=current_work_id(),
            owner_user_id=str(owner) if owner else None,
            goto=_goto,
            timeout_s=float(settings.structural_nav_timeout_s),
            turn_id=_kwargs.get("turn_id"),
            path_hint=None if path in {".", ""} else path,
        )
        if ast_out is not None:
            if ast_out.get("_ast_infra_failed"):
                reason = str(ast_out.get("reason") or "lsp_unavailable")
                # Keep candidates[] echo when present (§2.2.1); never as definitions.
                payload = {
                    "query": q,
                    "mode": "symbol",
                    "definitions": [],
                    "hits": [],
                    "match_count": 0,
                    "lines": list(ast_out.get("lines") or []),
                    "locate_incomplete": True,
                    "status": "failed",
                    "summary": (
                        f"search_codebase: language server required for symbol locate ({reason}); "
                        "fix runtime provider — lexical hits are not a successful Locate"
                    ),
                    **{
                        k: v
                        for k, v in ast_out.items()
                        if k
                        in {
                            "candidates",
                            "candidates_from",
                            "index_gen",
                            "locate_fuse_fail_reason",
                        }
                        and v is not None
                    },
                    **dict(ast_out.get("meta") or {}),
                }
                if "locate_fuse_fail_reason" not in payload:
                    fuse = "lsp_timeout" if "timeout" in reason else "lsp_failed"
                    payload["locate_fuse_fail_reason"] = fuse
                return payload
            return ast_out
    except Exception:
        # Index faults must never change interactive semantics (§2.2 / §8).
        pass

    out = await _goto(
        workspace,
        q,
        path=None if path in {".", ""} else path,
        timeout_s=float(settings.structural_nav_timeout_s),
        turn_id=_kwargs.get("turn_id"),
    )
    locations = list(out.get("locations") or [])
    lines = format_locations_lines(locations)
    meta = dict(out.get("meta") or {})
    reason = str(meta.get("degraded_reason") or "")
    if _lsp_infra_failed(reason):
        fuse = "lsp_timeout" if "timeout" in reason.lower() else "lsp_failed"
        return {
            "query": q,
            "mode": "symbol",
            "definitions": [],
            "hits": [],
            "match_count": 0,
            "lines": [],
            "locate_incomplete": True,
            "status": "failed",
            "locate_fuse_fail_reason": fuse,
            "summary": (
                f"search_codebase: language server required for symbol locate ({reason}); "
                "fix runtime provider — lexical hits are not a successful Locate"
            ),
            **meta,
        }

    definitions = [
        loc.to_dict() if hasattr(loc, "to_dict") else loc for loc in locations
    ]
    if definitions:
        return {
            "query": q,
            "mode": "symbol",
            "definitions": definitions,
            "hits": [],
            "match_count": len(definitions),
            "lines": lines,
            "locate_incomplete": False,
            "summary": (
                f"search_codebase (Locate): {len(definitions)} definition(s) for {q!r}"
            ),
            **meta,
        }

    # Structural miss only — lexical fallback allowed, never presented as complete Locate.
    from app.structural.symbols import is_non_definition_query

    lexical = await _lexical_codebase_hits(q, path=path, limit=limit, **_kwargs)
    hits = list(lexical.get("hits") or [])
    fuse = (
        "non_definition_query"
        if is_non_definition_query(q)
        else "no_workspace_symbol_match"
    )
    return {
        "query": q,
        "mode": "symbol",
        "definitions": [],
        "hits": hits,
        "match_count": len(hits),
        "lines": [],
        "locate_incomplete": True,
        "locate_fuse_fail_reason": fuse,
        "truncated": bool(lexical.get("truncated")),
        "files_scanned": int(lexical.get("files_scanned") or 0),
        "summary": (
            f"search_codebase: no definition for {q!r}; "
            f"lexical fallback {len(hits)} hit(s) — Locate incomplete"
            + (
                " (scan budget hit — results may be partial)"
                if lexical.get("truncated")
                else ""
            )
        ),
        **meta,
    }
