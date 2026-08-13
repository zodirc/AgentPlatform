"""Locate coarse-filter via AST index (§2.2 / §2.2.1).

Welded into search_codebase — no new tool name. Incomplete hits echo
``candidates[]`` (never as definitions). Fuse-fail reasons for CSI probes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.hashutil import hash_bytes
from app.structural.workspace_index.job import parse_single_file_fallback
from app.structural.workspace_index.query import normalize_symbol_query
from app.structural.workspace_index.service import get_ast_index_service
from app.structural.workspace_index.types import IndexStatus, SymbolHit

logger = logging.getLogger(__name__)

GotoFn = Callable[..., Awaitable[dict[str, Any]]]

# §0.3 probe buckets
FUSE_NO_WS_SYMBOL = "no_workspace_symbol_match"
FUSE_DEFINITION_NULL = "definition_null"
FUSE_LSP_FAILED = "lsp_failed"
FUSE_LSP_TIMEOUT = "lsp_timeout"


def _infra_fuse_reason(reason: str) -> str:
    r = (reason or "").lower()
    if "timeout" in r:
        return FUSE_LSP_TIMEOUT
    return FUSE_LSP_FAILED


def _line_snippet(workspace: Path, rel: str, line: int) -> str:
    try:
        text = (workspace / rel).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if 1 <= int(line) <= len(lines):
            return lines[int(line) - 1].rstrip()[:120]
    except OSError:
        pass
    return ""


def _candidate_dict(workspace: Path, hit: SymbolHit, *, symbol: str) -> dict[str, Any]:
    snippet = _line_snippet(workspace, hit.path, hit.line)
    kind = hit.kind or "symbol"
    line_proto = (
        f"{hit.path}:{hit.line}:{hit.col} {kind} {hit.name or symbol}"
        + (f" | {snippet}" if snippet else "")
    )
    return {
        "path": hit.path,
        "line": int(hit.line),
        "col": int(hit.col),
        "kind": kind,
        "symbol": hit.name or symbol,
        "container": hit.container,
        "snippet": snippet,
        "source": "ast_index",
        "confirmed": False,
        "line_proto": line_proto,
    }


def _incomplete_payload(
    *,
    symbol: str,
    hits: list[SymbolHit],
    workspace: Path,
    index_gen: int,
    fuse_reason: str,
    status: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top_k = max(1, int(settings.workspace_ast_locate_top_k))
    cands = [_candidate_dict(workspace, h, symbol=symbol) for h in hits[:top_k]]
    lines = [c["line_proto"] for c in cands if c.get("line_proto")]
    out: dict[str, Any] = {
        "query": symbol,
        "mode": "symbol",
        "definitions": [],
        "hits": [],
        "match_count": 0,
        "lines": lines,
        "locate_incomplete": True,
        "candidates": cands,
        "candidates_from": "ast_index",
        "index_gen": index_gen,
        "locate_fuse_fail_reason": fuse_reason,
        "summary": (
            f"search_codebase: no confirmed definition for {symbol!r}; "
            f"{len(cands)} AST candidate(s) — Locate incomplete ({fuse_reason})"
        ),
    }
    if status:
        out["status"] = status
    if meta:
        out.update(meta)
    return out


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

    Returns a search_codebase-shaped dict on success / incomplete-with-candidates,
    or None to fall through to today's LSP+lexical behavior.
    Never invents definitions without LSP confirmation (veto 3).
    """
    if work_id is None or not owner_user_id:
        return None
    service = get_ast_index_service()
    if not service.enabled_for_work(work_id=work_id, work_root=workspace):
        return None

    hits, meta = await service.lookup_symbol(
        work_id,
        symbol,
        owner_user_id=owner_user_id,
        limit=max(1, int(settings.workspace_ast_locate_top_k)),
        work_root=workspace,
    )
    if meta is None or meta.status in {IndexStatus.COLD, IndexStatus.ERROR}:
        return None
    if not hits:
        return None

    if path_hint and path_hint not in {".", ""}:
        prefix = path_hint.replace("\\", "/").lstrip("./")
        hits = [h for h in hits if h.path == prefix or h.path.startswith(prefix.rstrip("/") + "/")]
        if not hits:
            return None

    definitions: list[Any] = []
    used_hits: list[SymbolHit] = []
    index_gen = int(meta.generation)
    nq = normalize_symbol_query(symbol)
    last_infra: dict[str, Any] | None = None

    for hit in hits:
        abs_path = (workspace / hit.path).resolve()
        if not abs_path.is_file():
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
        try:
            st = abs_path.stat()
            size = int(st.st_size)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            proj = await service.ensure_projection(
                work_id, owner_user_id=owner_user_id, work_root=workspace
            )
            entry = proj.file_entry(hit.path) if proj else None
            stale = False
            if entry is None:
                stale = True
            elif entry.size != size or abs(entry.mtime_ns - mtime_ns) > 0:
                data = abs_path.read_bytes()
                if hash_bytes(data) != entry.content_hash:
                    stale = True
            if stale:
                corrected = parse_single_file_fallback(
                    abs_path, work_root=workspace, generation=index_gen
                )
                match = next(
                    (
                        s
                        for s in corrected
                        if s.name == hit.name or s.name == nq.tail
                    ),
                    None,
                )
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
            last_infra = {
                "reason": reason,
                "meta": meta_out,
                "fuse": _infra_fuse_reason(reason),
            }
            # Keep trying other candidates on timeout; infra-unavailable aborts.
            if reason in {"lsp_unavailable", "provider_missing", "unsupported_language"}:
                payload = _incomplete_payload(
                    symbol=symbol,
                    hits=hits,
                    workspace=workspace,
                    index_gen=index_gen,
                    fuse_reason=_infra_fuse_reason(reason),
                    status="failed",
                    meta=meta_out,
                )
                payload["_ast_infra_failed"] = True
                payload["reason"] = reason
                return payload
            continue

        locs = list(out.get("locations") or [])
        if locs:
            for loc in locs:
                definitions.append(loc.to_dict() if hasattr(loc, "to_dict") else loc)
            used_hits.append(hit)
            break

    if not definitions:
        fuse = (
            last_infra["fuse"]
            if last_infra is not None
            else FUSE_DEFINITION_NULL
        )
        status = "failed" if last_infra is not None else None
        meta_extra = dict(last_infra.get("meta") or {}) if last_infra else {}
        return _incomplete_payload(
            symbol=symbol,
            hits=hits,
            workspace=workspace,
            index_gen=index_gen,
            fuse_reason=fuse,
            status=status,
            meta=meta_extra or None,
        )

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
