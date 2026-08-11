"""Locate coarse-filter via AST index (§2.2). Welded into search_codebase — no new tool name."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.hashutil import hash_bytes
from app.structural.workspace_index.job import parse_single_file_fallback
from app.structural.workspace_index.service import get_ast_index_service
from app.structural.workspace_index.types import IndexStatus, SymbolHit

logger = logging.getLogger(__name__)

GotoFn = Callable[..., Awaitable[dict[str, Any]]]


async def locate_via_ast_index(
    *,
    workspace: Path,
    symbol: str,
    work_id: UUID | None,
    owner_user_id: str | None,
    goto: GotoFn,
    timeout_s: float,
    turn_id: object | None,
    path_hint: str | None = None,
) -> dict[str, Any] | None:
    """Try AST candidates → LSP confirmation.

    Returns a search_codebase-shaped dict on success/partial, or None to fall
    through to today's LSP+lexical behavior. Never invents definitions without LSP.
    """
    if work_id is None or not owner_user_id:
        return None
    service = get_ast_index_service()
    if not service.enabled_for_work(work_root=workspace):
        return None

    hits, meta = await service.lookup_symbol(
        work_id,
        symbol,
        owner_user_id=owner_user_id,
        limit=max(1, int(settings.workspace_ast_locate_top_k)),
    )
    if meta is None or meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
        return None
    if not hits:
        return None

    # Optional path scope: keep candidates under the requested subtree.
    if path_hint and path_hint not in {".", ""}:
        prefix = path_hint.replace("\\", "/").lstrip("./")
        hits = [h for h in hits if h.path == prefix or h.path.startswith(prefix.rstrip("/") + "/")]
        if not hits:
            return None

    definitions: list[Any] = []
    lines: list[str] = []
    used_hits: list[SymbolHit] = []
    index_gen = int(meta.generation)

    for hit in hits:
        abs_path = (workspace / hit.path).resolve()
        if not abs_path.is_file():
            # Ghost entry — enqueue delete via dirty when possible.
            try:
                from app.structural.workspace_index.dirty import notify_path_changed

                notify_path_changed(
                    hit.path,
                    work_id=work_id,
                    owner_user_id=owner_user_id,
                    work_root=workspace,
                    deleted=True,
                )
            except Exception:
                pass
            continue

        line, col = hit.line, hit.col
        # §4.1: light validation — size/mtime fast path; hash when suspicious.
        try:
            st = abs_path.stat()
            size = int(st.st_size)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            proj = (await service.ensure_projection(work_id, owner_user_id=owner_user_id))
            entry = proj.file_entry(hit.path) if proj else None
            stale = False
            if entry is None:
                stale = True
            elif entry.size != size or abs(entry.mtime_ns - mtime_ns) > 0:
                # mtime/size drift → hash authority
                data = abs_path.read_bytes()
                if hash_bytes(data) != entry.content_hash:
                    stale = True
            if stale:
                # Single-file instant parse correction; enqueue dirty refresh.
                corrected = parse_single_file_fallback(
                    abs_path, work_root=workspace, generation=index_gen
                )
                match = next((s for s in corrected if s.name == symbol), None)
                if match is None:
                    try:
                        from app.structural.workspace_index.dirty import notify_path_changed

                        notify_path_changed(
                            hit.path,
                            work_id=work_id,
                            owner_user_id=owner_user_id,
                            work_root=workspace,
                        )
                    except Exception:
                        pass
                    continue
                line, col = match.line, match.col
                try:
                    from app.structural.workspace_index.dirty import notify_path_changed

                    notify_path_changed(
                        hit.path,
                        work_id=work_id,
                        owner_user_id=owner_user_id,
                        work_root=workspace,
                    )
                except Exception:
                    pass
        except OSError:
            continue

        out = await goto(
            workspace,
            symbol,
            path=hit.path,
            line=line,
            col=col,
            timeout_s=timeout_s,
            turn_id=turn_id,
        )
        meta_out = dict(out.get("meta") or {})
        reason = str(meta_out.get("degraded_reason") or "")
        if reason in {
            "lsp_unavailable",
            "provider_missing",
            "unsupported_language",
            "timeout",
            "cancelled",
        }:
            # Infra failure — do not invent definitions from index (§2.2 branch ③).
            return {
                "_ast_infra_failed": True,
                "meta": meta_out,
                "reason": reason,
            }

        locs = list(out.get("locations") or [])
        if locs:
            for loc in locs:
                definitions.append(loc.to_dict() if hasattr(loc, "to_dict") else loc)
            used_hits.append(hit)
            # First confirmed hit is enough for Locate success (same schema as today).
            break

    if not definitions:
        return None

    from app.structural.format import format_locations_lines
    from app.structural.types import Location

    loc_objs: list[Location] = []
    for d in definitions:
        if isinstance(d, Location):
            loc_objs.append(d)
        elif isinstance(d, dict):
            loc_objs.append(
                Location(
                    path=str(d.get("path") or ""),
                    line=int(d.get("line") or 1),
                    col=int(d.get("col") or d.get("character") or 1),
                    kind=str(d.get("kind") or "def"),
                    symbol=str(d.get("symbol") or symbol),
                    snippet=str(d.get("snippet") or ""),
                )
            )
    lines = format_locations_lines(loc_objs) if loc_objs else []

    return {
        "query": symbol,
        "mode": "symbol",
        "definitions": definitions,
        "hits": [],
        "match_count": len(definitions),
        "lines": lines,
        "locate_incomplete": False,
        "summary": (
            f"search_codebase (Locate): {len(definitions)} definition(s) for {symbol!r}"
        ),
        "candidates_from": "ast_index",
        "index_gen": index_gen,
        "ast_candidates": [
            {"path": h.path, "line": h.line, "kind": h.kind} for h in used_hits
        ],
    }
