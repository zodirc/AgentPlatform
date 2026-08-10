from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.settings import settings
from app.structural.client import uri_to_path
from app.structural.format import (
    aggregate_refs_by_file,
    lsp_severity_to_str,
)
from app.structural.pool import get_session, mark_unhealthy
from app.structural.providers import language_for_path
from app.structural.types import Issue, Location

logger = logging.getLogger(__name__)


def structural_available() -> bool:
    return bool(settings.structural_enabled)


def _rel(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _snippet_at(path: Path, line: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if 1 <= line <= len(lines):
            return lines[line - 1].rstrip()[:120]
    except OSError:
        pass
    return ""


def _location_from_lsp(
    item: dict[str, Any],
    *,
    workspace: Path,
    kind: str,
    symbol: str,
) -> Location | None:
    # Location | LocationLink
    target = item.get("targetUri") or item.get("uri")
    rng = item.get("targetSelectionRange") or item.get("targetRange") or item.get("range")
    if not target or not isinstance(rng, dict):
        return None
    start = rng.get("start") or {}
    line = int(start.get("line", 0)) + 1
    col = int(start.get("character", 0)) + 1
    abs_path = Path(uri_to_path(str(target)))
    rel = _rel(abs_path, workspace)
    return Location(
        path=rel,
        line=line,
        col=col,
        kind=kind,
        symbol=symbol,
        snippet=_snippet_at(abs_path, line),
    )


def _issue_from_lsp(diag: dict[str, Any], *, rel_path: str) -> Issue:
    rng = diag.get("range") or {}
    start = rng.get("start") or {}
    code = diag.get("code")
    code_s = str(code) if code is not None else ""
    return Issue(
        path=rel_path,
        line=int(start.get("line", 0)) + 1,
        col=int(start.get("character", 0)) + 1,
        severity=lsp_severity_to_str(diag.get("severity")),
        message=str(diag.get("message") or "").strip() or "diagnostic",
        provider="lsp",
        code=code_s,
        sources=("lsp",),
    )


def collect_python_files(root: Path, *, max_files: int, max_depth: int = 4) -> list[Path]:
    if root.is_file():
        return [root] if language_for_path(root) == "python" else []
    if not root.is_dir():
        return []
    out: list[Path] = []
    root = root.resolve()
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > max_depth:
            continue
        # Skip common noise
        if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"} for part in rel.parts):
            continue
        out.append(path)
        if len(out) >= max_files:
            break
    return out


async def _cancelled(turn_id: object | None) -> bool:
    if turn_id is None:
        return False
    try:
        from uuid import UUID

        from app.controller.turn_controller import _check_cancel_flag

        tid = turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id))
        cancelled, _force = await _check_cancel_flag(tid)
        return bool(cancelled)
    except Exception:
        return False


async def _await_or_cancel(awaitable, *, turn_id: object | None, workspace: Path):
    """Await a coroutine, aborting LSP session if the Turn is cancelled."""
    task = asyncio.ensure_future(awaitable)
    while not task.done():
        if await _cancelled(turn_id):
            task.cancel()
            await mark_unhealthy(workspace)
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise asyncio.CancelledError()
        done, _ = await asyncio.wait({task}, timeout=0.25)
        if done:
            break
    return task.result()


async def get_diagnostics(
    workspace_root: Path,
    target: Path,
    *,
    timeout_s: float | None = None,
    turn_id: object | None = None,
) -> dict[str, Any]:
    """LSP diagnostics for a file or bounded directory. Degrades cleanly."""
    timeout = timeout_s if timeout_s is not None else float(settings.structural_diag_timeout_s)
    max_files = max(1, int(settings.structural_max_files_per_call))
    files = collect_python_files(target, max_files=max_files)
    meta: dict[str, Any] = {
        "provider": None,
        "cold_start": False,
        "truncated": False,
        "unsupported": False,
        "degraded_reason": None,
    }
    if not files:
        lang = language_for_path(target) if target.is_file() else None
        if target.is_file() and lang is None:
            meta["unsupported"] = True
            meta["degraded_reason"] = "unsupported_language"
            return {"issues": [], "meta": meta, "lines": []}
        return {"issues": [], "meta": meta, "lines": []}

    if await _cancelled(turn_id):
        meta["degraded_reason"] = "cancelled"
        return {"issues": [], "meta": meta, "lines": [], "status": "cancelled"}

    session, cold, reason = await get_session(workspace_root, timeout_s=min(timeout, 30.0))
    meta["cold_start"] = cold
    if session is None:
        meta["degraded_reason"] = reason or "lsp_unavailable"
        return {"issues": [], "meta": meta, "lines": []}

    meta["provider"] = session.provider.name
    issues: list[Issue] = []
    per_file_timeout = max(3.0, timeout / max(1, len(files)))
    try:
        for path in files:
            if await _cancelled(turn_id):
                meta["degraded_reason"] = "cancelled"
                return {"issues": issues, "meta": meta, "lines": [], "status": "cancelled"}
            diags = await _await_or_cancel(
                session.diagnostics_for(
                    path,
                    timeout_s=per_file_timeout,
                    language_id="python",
                ),
                turn_id=turn_id,
                workspace=workspace_root,
            )
            rel = _rel(path, workspace_root)
            for diag in diags:
                issues.append(_issue_from_lsp(diag, rel_path=rel))
        if target.is_dir() and len(files) >= max_files:
            meta["truncated"] = True
    except asyncio.CancelledError:
        meta["degraded_reason"] = "cancelled"
        return {"issues": issues, "meta": meta, "lines": [], "status": "cancelled"}
    except Exception as exc:
        logger.info("diagnostics failed: %s", exc)
        await mark_unhealthy(workspace_root)
        meta["degraded_reason"] = f"timeout_or_error:{type(exc).__name__}"
        return {"issues": [], "meta": meta, "lines": []}

    meta["cold_start"] = session.cold_start and cold
    return {"issues": issues, "meta": meta, "lines": []}


async def _resolve_symbol_positions(
    session: Any,
    workspace: Path,
    symbol: str,
    *,
    hint_path: Path | None,
    hint_line: int | None,
    hint_col: int | None,
    timeout_s: float,
) -> list[tuple[Path, int, int]]:
    """Symbol-name first; optional path/line/col as disambiguation."""
    if hint_path is not None and hint_line is not None and hint_col is not None:
        return [(hint_path.resolve(), hint_line, hint_col)]

    positions: list[tuple[Path, int, int]] = []
    try:
        symbols = await session.workspace_symbols(symbol, timeout_s=timeout_s)
    except Exception:
        symbols = []

    for item in symbols:
        name = str(item.get("name") or "")
        if name != symbol and not name.endswith("." + symbol):
            # Allow exact or suffix match only — avoid silent fuzzy greps.
            if symbol not in name:
                continue
            if name.split(".")[-1] != symbol and name != symbol:
                continue
        loc = item.get("location") or {}
        uri = loc.get("uri")
        rng = loc.get("range") or {}
        start = rng.get("start") or {}
        if not uri:
            continue
        abs_path = Path(uri_to_path(str(uri)))
        if hint_path is not None and abs_path.resolve() != hint_path.resolve():
            continue
        positions.append(
            (
                abs_path,
                int(start.get("line", 0)) + 1,
                int(start.get("character", 0)) + 1,
            )
        )

    if positions:
        return positions

    # Document-symbol fallback when a path hint is present.
    if hint_path is not None and hint_path.is_file():
        await session.ensure_open(hint_path, language_id="python")
        # Scan file for the symbol token as a last local hint (not grep-disguised refs).
        text = hint_path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            idx = line.find(symbol)
            if idx < 0:
                continue
            # Prefer definition-like lines
            stripped = line.lstrip()
            if stripped.startswith(("def ", "class ", "async def ")):
                return [(hint_path.resolve(), i, idx + 1)]
            if not positions:
                positions.append((hint_path.resolve(), i, idx + 1))
        if positions:
            return positions[:5]

    return []


async def goto_definition(
    workspace_root: Path,
    symbol: str,
    *,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    timeout_s: float | None = None,
    turn_id: object | None = None,
) -> dict[str, Any]:
    timeout = timeout_s if timeout_s is not None else float(settings.structural_nav_timeout_s)
    meta: dict[str, Any] = {
        "provider": None,
        "cold_start": False,
        "unsupported": False,
        "degraded_reason": None,
    }
    hint_path = (workspace_root / path).resolve() if path else None
    if hint_path is not None and hint_path.is_file():
        if language_for_path(hint_path) is None:
            meta["unsupported"] = True
            meta["degraded_reason"] = "unsupported_language"
            return {"locations": [], "lines": [], "meta": meta, "suggest": "grep"}

    if await _cancelled(turn_id):
        meta["degraded_reason"] = "cancelled"
        return {
            "locations": [],
            "lines": [],
            "meta": meta,
            "suggest": "grep",
            "status": "cancelled",
            "summary": "goto_definition cancelled",
        }

    session, cold, reason = await get_session(workspace_root, timeout_s=min(timeout, 20.0))
    meta["cold_start"] = cold
    if session is None:
        meta["degraded_reason"] = reason or "lsp_unavailable"
        return {
            "locations": [],
            "lines": [],
            "meta": meta,
            "suggest": "grep",
            "summary": "goto_definition unavailable; use grep for lexical search",
        }

    meta["provider"] = session.provider.name
    try:
        positions = await _await_or_cancel(
            _resolve_symbol_positions(
                session,
                workspace_root,
                symbol,
                hint_path=hint_path if hint_path and hint_path.is_file() else None,
                hint_line=line,
                hint_col=col,
                timeout_s=timeout,
            ),
            turn_id=turn_id,
            workspace=workspace_root,
        )
        if not positions:
            return {
                "locations": [],
                "lines": [],
                "meta": meta,
                "suggest": "grep",
                "summary": f"no symbol candidates for {symbol!r}; try grep",
            }
        locations: list[Location] = []
        seen: set[tuple[str, int, int]] = set()
        for abs_path, ln, cl in positions[:10]:
            if await _cancelled(turn_id):
                meta["degraded_reason"] = "cancelled"
                return {
                    "locations": locations,
                    "lines": [],
                    "meta": meta,
                    "status": "cancelled",
                    "summary": "goto_definition cancelled",
                }
            raw = await _await_or_cancel(
                session.definition(abs_path, ln, cl, timeout_s=timeout),
                turn_id=turn_id,
                workspace=workspace_root,
            )
            for item in raw:
                loc = _location_from_lsp(item, workspace=workspace_root, kind="def", symbol=symbol)
                if loc is None:
                    continue
                key = (loc.path, loc.line, loc.col)
                if key in seen:
                    continue
                seen.add(key)
                locations.append(loc)
        return {"locations": locations, "lines": [], "meta": meta}
    except asyncio.CancelledError:
        meta["degraded_reason"] = "cancelled"
        return {
            "locations": [],
            "lines": [],
            "meta": meta,
            "suggest": "grep",
            "status": "cancelled",
            "summary": "goto_definition cancelled",
        }
    except Exception as exc:
        logger.info("goto_definition failed: %s", exc)
        await mark_unhealthy(workspace_root)
        meta["degraded_reason"] = f"timeout_or_error:{type(exc).__name__}"
        return {
            "locations": [],
            "lines": [],
            "meta": meta,
            "suggest": "grep",
            "summary": "goto_definition failed; use grep",
        }


async def find_references(
    workspace_root: Path,
    symbol: str,
    *,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    timeout_s: float | None = None,
    turn_id: object | None = None,
) -> dict[str, Any]:
    timeout = timeout_s if timeout_s is not None else float(settings.structural_nav_timeout_s)
    max_refs = max(1, int(settings.structural_max_refs))
    meta: dict[str, Any] = {
        "provider": None,
        "cold_start": False,
        "truncated": False,
        "unsupported": False,
        "degraded_reason": None,
    }
    hint_path = (workspace_root / path).resolve() if path else None
    if await _cancelled(turn_id):
        meta["degraded_reason"] = "cancelled"
        return {
            "locations": [],
            "lines": [],
            "pointers": [],
            "meta": meta,
            "suggest": "grep",
            "status": "cancelled",
            "summary": "find_references cancelled",
        }
    session, cold, reason = await get_session(workspace_root, timeout_s=min(timeout, 20.0))
    meta["cold_start"] = cold
    if session is None:
        meta["degraded_reason"] = reason or "lsp_unavailable"
        return {
            "locations": [],
            "lines": [],
            "pointers": [],
            "meta": meta,
            "suggest": "grep",
            "summary": "find_references unavailable; use grep (do not treat lexical hits as refs)",
        }

    meta["provider"] = session.provider.name
    try:
        positions = await _await_or_cancel(
            _resolve_symbol_positions(
                session,
                workspace_root,
                symbol,
                hint_path=hint_path if hint_path and hint_path.is_file() else None,
                hint_line=line,
                hint_col=col,
                timeout_s=timeout,
            ),
            turn_id=turn_id,
            workspace=workspace_root,
        )
        if not positions:
            return {
                "locations": [],
                "lines": [],
                "pointers": [],
                "meta": meta,
                "suggest": "grep",
                "summary": f"no symbol candidates for {symbol!r}; try grep",
            }
        locations: list[Location] = []
        seen: set[tuple[str, int, int]] = set()
        abs_path, ln, cl = positions[0]
        raw = await _await_or_cancel(
            session.references(abs_path, ln, cl, timeout_s=timeout),
            turn_id=turn_id,
            workspace=workspace_root,
        )
        for item in raw:
            loc = _location_from_lsp(item, workspace=workspace_root, kind="ref", symbol=symbol)
            if loc is None:
                continue
            key = (loc.path, loc.line, loc.col)
            if key in seen:
                continue
            seen.add(key)
            locations.append(loc)
        kept, pointers, truncated = aggregate_refs_by_file(locations, max_refs=max_refs)
        meta["truncated"] = truncated
        return {
            "locations": kept,
            "pointers": pointers,
            "lines": [],
            "meta": meta,
        }
    except asyncio.CancelledError:
        meta["degraded_reason"] = "cancelled"
        return {
            "locations": [],
            "lines": [],
            "pointers": [],
            "meta": meta,
            "suggest": "grep",
            "status": "cancelled",
            "summary": "find_references cancelled",
        }
    except Exception as exc:
        logger.info("find_references failed: %s", exc)
        await mark_unhealthy(workspace_root)
        meta["degraded_reason"] = f"timeout_or_error:{type(exc).__name__}"
        return {
            "locations": [],
            "lines": [],
            "pointers": [],
            "meta": meta,
            "suggest": "grep",
            "summary": "find_references failed; use grep",
        }


async def prewarm(workspace_root: Path) -> None:
    """Best-effort background initialize — never awaited on StartTurn."""
    if not settings.structural_enabled or not settings.structural_prewarm:
        return
    try:
        await get_session(workspace_root, timeout_s=float(settings.structural_nav_timeout_s))
    except Exception:
        pass
