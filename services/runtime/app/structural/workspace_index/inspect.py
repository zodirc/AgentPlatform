"""Settings inspect: AST index files + nested definition tree. Off-loop only."""

from __future__ import annotations

from typing import Any

from app.structural.workspace_index.types import FileEntry, SymbolRec

_MAX_FILES = 400
_MAX_SYMBOLS = 400


def nest_symbols(symbols: list[SymbolRec]) -> list[dict[str, Any]]:
    """Nest definition rows by ``container`` chain (class.method outline)."""
    nodes: list[dict[str, Any]] = []
    by_qual: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        qual = f"{sym.container}.{sym.name}" if sym.container else sym.name
        node = {
            "name": sym.name,
            "kind": sym.kind,
            "line": int(sym.line),
            "col": int(sym.col),
            "end_line": int(sym.end_line) if sym.end_line is not None else None,
            "container": sym.container,
            "qual": qual,
            "children": [],
        }
        nodes.append(node)
        # Last write wins for parent lookup; overloads still appear as siblings.
        by_qual[qual] = node

    roots: list[dict[str, Any]] = []
    for node in nodes:
        parent_qual = node["container"]
        parent = by_qual.get(parent_qual) if parent_qual else None
        if parent is not None and parent is not node:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


def format_symbol_tree(symbols: list[SymbolRec], *, path: str = "") -> str:
    """ASCII tree of indexed definitions — the inspect surface for Settings."""
    roots = nest_symbols(symbols)
    lines: list[str] = []
    if path:
        lines.append(path)

    def walk(node: dict[str, Any], prefix: str, is_last: bool, *, top: bool) -> None:
        branch = "" if top and not prefix else ("└── " if is_last else "├── ")
        span = f"L{node['line']}"
        if node.get("end_line"):
            span += f"–{node['end_line']}"
        lines.append(f"{prefix}{branch}{node['kind']} {node['name']}  {span}")
        kids = node.get("children") or []
        child_prefix = prefix + ("" if top and not prefix else ("    " if is_last else "│   "))
        for i, child in enumerate(kids):
            walk(child, child_prefix, i == len(kids) - 1, top=False)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1, top=not bool(path))
    return "\n".join(lines) if lines else "(no symbols)"


def _file_summary(entry: FileEntry) -> dict[str, Any]:
    return {
        "path": entry.path,
        "lang": entry.lang,
        "size": int(entry.size),
        "generation": int(entry.generation),
        "symbol_count": len(entry.symbols),
        "import_count": len(entry.imports),
    }


def _symbol_payload(sym: SymbolRec) -> dict[str, Any]:
    return {
        "name": sym.name,
        "kind": sym.kind,
        "line": int(sym.line),
        "col": int(sym.col),
        "end_line": int(sym.end_line) if sym.end_line is not None else None,
        "container": sym.container,
    }


async def inspect_ast_index(
    *,
    work_id,
    owner_user_id: str,
    work_root=None,
    path: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List AST files or dump one file's definition tree."""
    from uuid import UUID

    from app.structural.workspace_index.service import get_ast_index_service

    wid = work_id if isinstance(work_id, UUID) else UUID(str(work_id))
    service = get_ast_index_service()
    if not service.enabled_for_work(work_id=wid, work_root=work_root):
        return {
            "enabled": False,
            "status": "disabled",
            "files": [],
            "total": 0,
            "file": None,
        }
    proj = await service.ensure_projection(
        wid, owner_user_id=owner_user_id, work_root=work_root
    )
    if proj is not None and work_root is not None:
        from pathlib import Path as _Path

        from app.structural.workspace_index.watch import (
            gc_missing_indexed_files,
            register_active_work,
        )

        root = _Path(work_root)
        register_active_work(wid, owner_user_id=owner_user_id, work_root=root)
        gc_missing_indexed_files(
            work_id=wid,
            owner_user_id=owner_user_id,
            work_root=root,
        )
    if proj is None:
        meta = await service.status(
            wid, owner_user_id=owner_user_id, work_root=work_root
        )
        return {
            "enabled": True,
            "status": meta.get("status") or "cold",
            "files": [],
            "total": 0,
            "file": None,
            "generation": meta.get("generation") or 0,
        }

    cap = max(1, min(_MAX_FILES, int(limit)))
    needle = (q or "").strip().lower()
    entries = sorted(proj.files.values(), key=lambda e: e.path)
    if needle:
        entries = [e for e in entries if needle in e.path.lower()]
    summaries = [_file_summary(e) for e in entries]
    payload: dict[str, Any] = {
        "enabled": True,
        "status": proj.meta.status.value,
        "generation": int(proj.meta.generation),
        "files": summaries[:cap],
        "total": len(summaries),
        "truncated": len(summaries) > cap,
        "file": None,
    }
    rel = (path or "").strip().lstrip("/")
    if not rel:
        return payload
    entry = proj.files.get(rel)
    if entry is None:
        payload["file"] = {"path": rel, "missing": True}
        return payload
    symbols = entry.symbols[:_MAX_SYMBOLS]
    payload["file"] = {
        "path": entry.path,
        "lang": entry.lang,
        "size": int(entry.size),
        "generation": int(entry.generation),
        "missing": False,
        "imports": list(entry.imports)[:80],
        "symbols": [_symbol_payload(s) for s in symbols],
        "symbol_truncated": len(entry.symbols) > _MAX_SYMBOLS,
        "tree": nest_symbols(symbols),
        "tree_text": format_symbol_tree(symbols, path=entry.path),
    }
    return payload
