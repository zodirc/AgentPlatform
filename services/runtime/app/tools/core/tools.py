from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.settings import settings


def _resolve_path(rel_path: str) -> Path:
    root = Path(settings.workspace_root).resolve()
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root)):
        raise PermissionError(f"Path outside workspace: {rel_path}")
    return target


def _normalized_workspace_rel(rel_path: str) -> str:
    return rel_path.strip().lstrip("/").replace("\\", "/")


def is_seed_corpus_path(rel_path: str) -> bool:
    """True for standing seed corpus under sources/seed/ (RO mount; docs/15)."""
    normalized = _normalized_workspace_rel(rel_path)
    return normalized == "sources/seed" or normalized.startswith("sources/seed/")


def _assert_not_seed_corpus(rel_path: str) -> None:
    if is_seed_corpus_path(rel_path):
        raise PermissionError(
            "seed corpus is read-only; edit files under seed/sources/writing in the repo"
        )


async def read_file(path: str, **_kwargs: Any) -> dict[str, Any]:
    """Read a workspace file.

    For writing monofile manuscripts (docs/24): default returns one chapter block
    when ``section_id`` is set; without it returns a section index unless
    ``full=true`` / full-book intent.
    """
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    if not target.is_file():
        return {"error": f"Not a file: {path}"}
    content = target.read_text(encoding="utf-8", errors="replace")

    from app.writing.focus import wants_full_manuscript_read
    from app.writing.manuscript import (
        clip_text,
        extract_section,
        is_manuscript_rel,
        list_section_ids,
    )

    section_id = str(_kwargs.get("section_id") or "").strip()
    full_flag = str(_kwargs.get("full", "")).lower() in {"1", "true", "yes"}
    economy = bool(getattr(settings, "writing_token_economy_enabled", True))

    if economy and is_manuscript_rel(path) and "<!-- section:" in content:
        sections = list_section_ids(content)
        if wants_full_manuscript_read(full_flag=full_flag):
            clipped, was = clip_text(content, 48_000)
            return {
                "path": path,
                "content": clipped,
                "full_manuscript": True,
                "clipped": was,
                "sections": sections,
                "writing_section_extract": False,
            }
        if section_id:
            body = extract_section(content, section_id)
            if body is None:
                return {
                    "path": path,
                    "error": f"section not found: {section_id}",
                    "sections": sections,
                    "hint": "Use a section_id from `sections`, or omit it to list chapters",
                }
            max_chars = int(getattr(settings, "writing_focus_max_chars", 12_000) or 12_000)
            clipped, was = clip_text(body, max_chars)
            return {
                "path": path,
                "section_id": section_id,
                "content": clipped,
                "clipped": was,
                "sections": sections,
                "writing_section_extract": True,
                "summary": f"Chapter `{section_id}` from {path}"
                + (" (clipped with visible omission)" if was else ""),
            }
        # Index-only default — avoid dumping the whole book into context.
        listing = ", ".join(sections[:40]) if sections else "(no section markers)"
        return {
            "path": path,
            "content": (
                f"Manuscript index for `{path}` (not full text).\n"
                f"Sections: {listing}\n"
                "Re-call read_file with section_id=\"chN\" to load one chapter. "
                "Set full=true only for whole-book review."
            ),
            "sections": sections,
            "truncated_to_index": True,
            "writing_section_extract": True,
            "hint": "Pass section_id to read one chapter; full=true for entire file",
        }

    if len(content) > 32_000:
        content = content[:32_000] + "\n...[truncated]"
    return {"path": path, "content": content}


async def list_dir(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"Directory not found: {path}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {path}"}
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
    return {"path": path, "entries": entries[:200]}


async def propose_patch(
    path: str,
    old_text: str,
    new_text: str,
    summary: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    _assert_not_seed_corpus(path)
    patch_id = f"patch-{uuid4().hex[:12]}"
    return {
        "patch_id": patch_id,
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "summary": summary or f"Proposed changes to {path}",
        "status": "pending",
    }


async def apply_patch(
    path: str,
    new_text: str,
    old_text: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Apply a patch surgically when ``old_text`` is set; otherwise full-file write.

    ``propose_patch`` emits ``old_text``/``new_text`` *spans*. Writing the span alone
    as the whole file destroys long documents after auto-apply.
    """
    _assert_not_seed_corpus(path)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    old = old_text or ""
    force = str(_kwargs.get("force_full_replace", "")).lower() in {"1", "true", "yes"}

    if old:
        count = existing.count(old)
        if count == 0:
            return {
                "path": path,
                "status": "error",
                "error": "old_text not found in current file; re-read and repropose",
            }
        if count > 1:
            return {
                "path": path,
                "status": "error",
                "error": f"old_text matches {count} times; use a longer unique span",
            }
        final = existing.replace(old, new_text, 1)
    else:
        if (
            not force
            and len(existing) >= 500
            and len(new_text) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "path": path,
                "status": "error",
                "error": (
                    f"refusing full replace that shrinks {len(existing)}→{len(new_text)} chars; "
                    "pass old_text for a surgical edit, or force_full_replace=true for intentional rewrite"
                ),
            }
        final = new_text

    target.write_text(final, encoding="utf-8")
    return {
        "path": path,
        "status": "applied",
        "bytes_written": len(final.encode("utf-8")),
        "mode": "surgical" if old else "full",
    }


def _section_filename(section_id: str) -> str:
    normalized = section_id.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid section_id: {section_id!r}")
    return f"{normalized}.md"


def _turn_scope(turn_id: object | None) -> str:
    return str(turn_id) if turn_id is not None else "standalone"


def _session_scope(session_id: object | None) -> str | None:
    if session_id is None:
        return None
    return str(session_id)


_WORK_DRAFTS = ".agent/work/drafts"
_WORK_HISTORY = ".agent/work/history"
_WORK_TURNS = ".agent/work/turns"


def _draft_file_path(section_id: str) -> str:
    """Canonical in-progress draft path (work-scoped, not session-scoped)."""
    return f"{_WORK_DRAFTS}/{_section_filename(section_id)}"


def _history_file_path(section_id: str, turn_id: object | None) -> str:
    return f"{_WORK_HISTORY}/{section_id.strip()}/{_turn_scope(turn_id)}.md"


def _manifest_path(session_id: object | None, turn_id: object | None) -> str:
    """Primary turn touch-list (work-scoped). ``session_id`` kept for API compat."""
    del session_id  # work-scoped; session no longer owns manifests
    return f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"


def _manifest_candidate_paths(session_id: object | None, turn_id: object | None) -> list[str]:
    """Read order: work turn → session legacy → flat turn legacy."""
    paths: list[str] = [f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"]
    if session_id is not None and turn_id is not None:
        legacy_session = (
            f".agent/sessions/{_session_scope(session_id)}/turns/"
            f"{_turn_scope(turn_id)}/manifest.json"
        )
        paths.append(legacy_session)
    if turn_id is not None:
        legacy = f".agent/turns/{_turn_scope(turn_id)}/manifest.json"
        if legacy not in paths:
            paths.append(legacy)
    return paths


def _revision_file_path(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> str:
    """Write target for ``draft_section`` — always work drafts."""
    del session_id, turn_id
    return _draft_file_path(section_id)


def _revision_candidate_paths(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> list[str]:
    """Read order: work draft → session/turn legacy → flat legacy."""
    filename = _section_filename(section_id)
    paths: list[str] = [_draft_file_path(section_id)]
    if session_id is not None and turn_id is not None:
        session_path = (
            f".agent/sessions/{_session_scope(session_id)}/revisions/"
            f"{_turn_scope(turn_id)}/{filename}"
        )
        if session_path not in paths:
            paths.append(session_path)
    if turn_id is not None:
        turn_path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
        if turn_path not in paths:
            paths.append(turn_path)
    legacy_flat = f".agent/revisions/{filename}"
    if legacy_flat not in paths:
        paths.append(legacy_flat)
    return paths


def _is_legacy_revision_rel(rel_path: str, filename: str) -> bool:
    """True for pre-work-model flat revision files (export warning)."""
    return rel_path == f".agent/revisions/{filename}"


def _prune_section_history(section_id: str, *, keep: int) -> None:
    if keep <= 0:
        return
    root = _resolve_path(f"{_WORK_HISTORY}/{section_id.strip()}")
    if not root.is_dir():
        return
    files = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix == ".md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            continue


def _read_manifest(
    turn_id: object | None,
    *,
    session_id: object | None = None,
) -> dict[str, Any] | None:
    for rel in _manifest_candidate_paths(session_id, turn_id):
        target = _resolve_path(rel)
        if not target.is_file():
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _write_manifest(
    turn_id: object | None,
    manifest: dict[str, Any],
    *,
    session_id: object | None = None,
) -> str:
    path = _manifest_path(session_id, turn_id)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return path


async def draft_section(
    section_id: str,
    content: str,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.writing.manuscript import (
        draft_manuscript_rel,
        manuscript_mode,
        upsert_section,
    )

    layout = str(_kwargs.get("layout") or manuscript_mode()).strip().lower()
    if layout not in {"monofile", "sections"}:
        layout = manuscript_mode()

    if layout == "monofile":
        path = draft_manuscript_rel()
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        final = upsert_section(existing, section_id, content)
        target.write_text(final, encoding="utf-8")
    else:
        path = _draft_file_path(section_id)
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    history_path: str | None = None
    keep = int(getattr(settings, "writing_draft_history_keep", 5) or 0)
    if keep > 0 and turn_id is not None:
        history_path = _history_file_path(section_id, turn_id)
        hist = _resolve_path(history_path)
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text(content, encoding="utf-8")
        _prune_section_history(section_id, keep=keep)

    manifest = _read_manifest(turn_id, session_id=session_id) or {
        "turn_id": _turn_scope(turn_id),
        "session_id": _session_scope(session_id),
        "sections": [],
        "revisions": {},
        "layout": layout,
    }
    if session_id is not None and not manifest.get("session_id"):
        manifest["session_id"] = _session_scope(session_id)
    manifest["layout"] = layout
    sections = manifest.setdefault("sections", [])
    revisions = manifest.setdefault("revisions", {})
    if section_id not in sections:
        sections.append(section_id)
    revisions[section_id] = path
    manifest_path = _write_manifest(turn_id, manifest, session_id=session_id)
    result: dict[str, Any] = {
        "section_id": section_id,
        "path": path,
        "manifest_path": manifest_path,
        "status": "drafted",
        "layout": layout,
    }
    if history_path:
        result["history_path"] = history_path
    return result


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
    from app.tools.core.shell import run_shell_command

    if settings.run_command_mode == "simulate":
        return {
            "status": "executed",
            "command": command,
            "stdout": f"[simulated] {command}",
            "exit_code": 0,
            "summary": f"Simulated: {command[:80]}",
        }

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    root = Path(settings.workspace_root).resolve()
    return await run_shell_command(
        command=command,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
        check_cancel=check_cancel,
    )


async def update_plan(
    items: list[dict[str, Any]],
    summary: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    plan_id = f"plan-{uuid4().hex[:8]}"
    normalized: list[dict[str, str]] = []
    for i, item in enumerate(items):
        normalized.append(
            {
                "id": str(item.get("id", i + 1)),
                "title": str(item.get("title", item.get("text", "item"))),
                "status": str(item.get("status", "pending")),
            }
        )
    return {
        "plan_id": plan_id,
        "items": normalized,
        "summary": summary or f"Plan with {len(normalized)} item(s)",
    }


async def update_outline(
    content: str,
    mode: str = "replace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Replace or append ``outline.md``.

    ``mode=append`` is the safe path for long outlines / batch continuation.
    Catastrophic shrink on ``replace`` is rejected unless ``force=true``.
    """
    path = "outline.md"
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    mode_n = (mode or "replace").strip().lower()
    force = str(_kwargs.get("force", "")).lower() in {"1", "true", "yes"}

    if mode_n == "append":
        if existing and not existing.endswith("\n"):
            sep = "\n\n"
        elif existing:
            sep = "\n" if not existing.endswith("\n\n") else ""
        else:
            sep = ""
        final = f"{existing}{sep}{content.lstrip()}" if existing else content
        summary = "Outline appended"
    else:
        if (
            not force
            and len(existing) >= 500
            and len(content) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "status": "error",
                "error": (
                    f"refusing outline replace that shrinks {len(existing)}→{len(content)} chars; "
                    "use mode=append for continuation, or force=true for intentional full rewrite"
                ),
                "outline_path": path,
                "existing_chars": len(existing),
            }
        final = content
        summary = "Outline updated"

    target.write_text(final, encoding="utf-8")
    return {
        "path": path,
        "content": final,
        "summary": summary,
        "outline_path": path,
        "mode": "append" if mode_n == "append" else "replace",
    }


async def grep(pattern: str, path: str = ".", limit: int = 50, **_kwargs: Any) -> dict[str, Any]:
    root = _resolve_path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}"}
    rx = re.compile(pattern, re.I)
    matches: list[dict[str, Any]] = []
    files = [root] if root.is_file() else list(root.rglob("*"))
    for fp in files:
        if not fp.is_file() or fp.name.startswith("."):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(fp.relative_to(Path(settings.workspace_root).resolve()))
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append({"path": rel, "line": i, "text": line[:240]})
                if len(matches) >= limit:
                    break
        if len(matches) >= limit:
            break
    return {
        "pattern": pattern,
        "matches": matches,
        "match_count": len(matches),
        "summary": f"Found {len(matches)} match(es) for {pattern!r}",
    }


async def sync_sources_index() -> dict[str, Any]:
    """Incremental sources projection (mtime dirty-set). Prefer scheduler for single-flight."""
    from app.retrieval.index_scheduler import run_sources_index_sync

    return await run_sources_index_sync(reason="api")


def _format_source_hits(hits: list[Any], *, excerpt_chars: int) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for hit in hits:
        excerpt = str(getattr(hit, "excerpt", "")).strip()
        if len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars] + "…"
        item: dict[str, Any] = {
            "path": str(getattr(hit, "path", "")),
            "chunk_id": str(getattr(hit, "chunk_id", "")),
            "excerpt": excerpt,
            "citation_id": str(getattr(hit, "citation_id", "")),
            "score": round(float(getattr(hit, "score", 0.0)), 4),
        }
        section_title = str(getattr(hit, "section_title", "")).strip()
        if section_title:
            item["section_title"] = section_title
        line_start = getattr(hit, "line_start", None)
        line_end = getattr(hit, "line_end", None)
        if line_start is not None:
            item["line_start"] = line_start
        if line_end is not None:
            item["line_end"] = line_end
        formatted.append(item)
    return formatted


def _search_sources_keyword(
    sources: Path,
    *,
    workspace_root: Path,
    query: str,
    limit: int,
    path_prefix: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.retrieval.chunking import should_index_source
    from app.retrieval.keyword_hit import keyword_hit_from_file
    from app.retrieval.path_filter import normalize_path_prefix, path_matches_prefix

    normalized, err = normalize_path_prefix(path_prefix)
    if err:
        return [], {
            "filters": {"path_prefix": path_prefix, "applied": False, "error": err},
            "hint": err,
        }

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    hits: list[dict[str, Any]] = []
    excerpt_chars = settings.search_sources_excerpt_chars
    max_bytes = settings.search_sources_keyword_max_file_bytes
    budget_ms = settings.search_sources_keyword_parse_budget_ms
    for fp in sorted(sources.rglob("*")):
        if not fp.is_file() or not should_index_source(fp):
            continue
        rel = str(fp.relative_to(workspace_root))
        if normalized is not None and not path_matches_prefix(rel, normalized):
            continue
        hit = keyword_hit_from_file(
            fp,
            rel_path=rel,
            terms=terms,
            excerpt_chars=excerpt_chars,
            max_file_bytes=max_bytes,
            parse_budget_ms=budget_ms,
        )
        if hit is None:
            continue
        hits.append(hit)
        if len(hits) >= limit:
            break
    meta: dict[str, Any] = {}
    if normalized is not None:
        meta["filters"] = {"path_prefix": normalized, "applied": True}
    return hits, meta


def _attach_filter_meta(payload: dict[str, Any], filter_meta: dict[str, Any]) -> dict[str, Any]:
    if not filter_meta:
        return payload
    if "filters" in filter_meta:
        payload["filters"] = filter_meta["filters"]
    if filter_meta.get("hint") and not payload.get("hint"):
        payload["hint"] = filter_meta["hint"]
    return payload


async def search_sources(
    query: str,
    limit: int = 10,
    path_prefix: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    from pathlib import Path

    from app.retrieval.path_filter import filter_hits_by_path_prefix
    from app.retrieval.store import get_sources_store

    sources = _resolve_path("sources")
    if not sources.exists():
        return {"query": query, "hits": [], "summary": "No sources directory", "retrieval": "none"}

    mode = settings.retrieval_mode.lower()
    workspace_root = Path(settings.workspace_root).resolve()
    excerpt_chars = settings.search_sources_excerpt_chars

    if mode == "keyword":
        hits, filter_meta = _search_sources_keyword(
            sources,
            workspace_root=workspace_root,
            query=query,
            limit=limit,
            path_prefix=path_prefix,
        )
        payload = {
            "query": query,
            "hits": hits,
            "summary": f"search_sources(keyword): {len(hits)} hit(s)",
            "retrieval": "keyword",
        }
        return _attach_filter_meta(payload, filter_meta)

    # Hot path: load + search only. Never store.sync() here (A9 / docs/13 S2).
    store = get_sources_store()
    index_meta: dict[str, Any] = {
        "synced_on_query": False,
        "index_via_worker": settings.index_via_worker,
    }
    # Over-fetch when filtering so prefix cuts do not starve top-k.
    fetch_limit = limit * 3 if path_prefix else limit
    try:
        store.load()
        raw_hits = store.search(query, limit=fetch_limit, mode=mode)
        retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"
    except OSError:
        index_meta["error"] = "vector_index_unavailable"
        raw_hits = []
        retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"

    if raw_hits:
        filtered, filter_meta = filter_hits_by_path_prefix(raw_hits, path_prefix=path_prefix)
        if filter_meta.get("filters", {}).get("error"):
            payload = {
                "query": query,
                "hits": [],
                "summary": "search_sources: invalid path_prefix",
                "retrieval": retrieval,
                "index": index_meta,
            }
            return _attach_filter_meta(payload, filter_meta)
        hits = _format_source_hits(filtered[:limit], excerpt_chars=excerpt_chars)
        if hits:
            payload = {
                "query": query,
                "hits": hits,
                "summary": f"search_sources({retrieval}): {len(hits)} hit(s)",
                "retrieval": retrieval,
                "index": index_meta,
            }
            _attach_filter_meta(payload, filter_meta)
            if hits[0].get("score", 0.0) < settings.search_sources_low_score_hint:
                top_path = hits[0].get("path", "")
                payload["hint"] = (
                    "Low relevance scores; prefer read_file on the top path "
                    f"({top_path}) instead of repeating search_sources."
                )
            return payload
        # ANN returned hits, but path_prefix removed them all (stale/shared index,
        # or over-fetch still missed the prefix). Fall through to keyword under the
        # same filter so eval / remounted workspaces still resolve on-disk sources.
        index_meta["prefix_empty_after_filter"] = True

    # Empty/stale index: keyword filesystem scan (no rebuild), plus lag hint.
    index_meta["index_lag"] = True
    index_meta["hint"] = (
        "Vector index empty or lagging; search used keyword fallback. "
        "Rebuild via sync_sources_index / worker upload path — not on query."
    )
    hits, filter_meta = _search_sources_keyword(
        sources,
        workspace_root=workspace_root,
        query=query,
        limit=limit,
        path_prefix=path_prefix,
    )
    payload = {
        "query": query,
        "hits": hits,
        "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
        "retrieval": "keyword-fallback",
        "index": index_meta,
        "hint": index_meta["hint"],
    }
    return _attach_filter_meta(payload, filter_meta)


async def search_codebase(query: str, path: str = ".", limit: int = 20, **_kwargs: Any) -> dict[str, Any]:
    result = await grep(pattern=re.escape(query), path=path, limit=limit, **_kwargs)
    return {
        "query": query,
        "hits": result.get("matches", []),
        "summary": result.get("summary", f"search_codebase: {query}"),
    }


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


async def glob(pattern: str, path: str = ".", limit: int = 100, **_kwargs: Any) -> dict[str, Any]:
    root = _resolve_path(path)
    if not root.exists():
        return {"error": f"Path not found: {path}", "matches": []}
    base = root if root.is_dir() else root.parent
    matches: list[str] = []
    for fp in sorted(base.glob(pattern)):
        if not fp.is_file():
            continue
        rel = str(fp.relative_to(Path(settings.workspace_root).resolve()))
        matches.append(rel)
        if len(matches) >= limit:
            break
    return {
        "pattern": pattern,
        "path": path,
        "matches": matches,
        "match_count": len(matches),
        "summary": f"glob {pattern!r}: {len(matches)} file(s)",
    }


async def write_file(path: str, content: str, **_kwargs: Any) -> dict[str, Any]:
    from app.privacy.secret_scan import gate_write_content

    _assert_not_seed_corpus(path)
    blocked = gate_write_content(content, path=path)
    if blocked is not None:
        return blocked
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "path": path,
        "bytes_written": len(content.encode()),
        "summary": f"Wrote {path}",
        "status": "written",
    }


async def edit_file(path: str, old_text: str, new_text: str, **_kwargs: Any) -> dict[str, Any]:
    _assert_not_seed_corpus(path)
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    if old_text not in text:
        return {"error": "old_text not found", "path": path}
    updated = text.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")
    return {
        "path": path,
        "summary": f"Edited {path}",
        "status": "edited",
    }


async def run_tests(command: str = "pytest -q", turn_id=None, **_kwargs: Any) -> dict[str, Any]:
    from app.tools.core.shell import run_shell_command

    if settings.run_command_mode == "simulate":
        return {
            "command": command,
            "status": "passed",
            "stdout": "[simulated] 3 passed",
            "exit_code": 0,
            "summary": f"Simulated tests: {command}",
        }

    check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None

    root = Path(settings.workspace_root).resolve()
    result = await run_shell_command(
        command=command,
        cwd=root,
        timeout_s=settings.tool_default_timeout_seconds,
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
    }


async def read_lints(path: str = ".", **_kwargs: Any) -> dict[str, Any]:
    import shlex

    from app.tools.core.shell import run_shell_command

    root = _resolve_path(path)
    workspace = Path(settings.workspace_root).resolve()
    rel = "." if path in {".", ""} else str(root.relative_to(workspace))

    result = await run_shell_command(
        command=f"python -m ruff check {shlex.quote(rel)} --output-format concise",
        cwd=workspace,
        timeout_s=min(settings.tool_default_timeout_seconds, 120.0),
    )
    stdout = str(result.get("stdout", ""))
    stderr = str(result.get("stderr", ""))
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    issues: list[dict[str, Any]] = []
    for line in combined.splitlines():
        line = line.strip()
        if not line:
            continue
        issues.append({"path": rel, "severity": "warning", "message": line})

    if result.get("status") == "executed" and not issues:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": f"read_lints: {rel} — no issues",
        }
    if result.get("status") == "failed" and issues:
        return {
            "path": path,
            "issues": issues,
            "issue_count": len(issues),
            "summary": f"read_lints: {len(issues)} issue(s) in {rel}",
        }
    if result.get("status") in {"timeout", "cancelled"}:
        return {
            "path": path,
            "issues": [],
            "issue_count": 0,
            "summary": str(result.get("summary", "read_lints interrupted")),
            "status": result.get("status"),
        }

    # ruff not installed or path missing — fall back to file scan count
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = [p for p in root.rglob("*.py") if p.is_file()][:20]
    else:
        return {"path": path, "issues": [], "summary": "No lint targets"}
    for fp in files:
        rel_fp = str(fp.relative_to(workspace))
        issues.append({"path": rel_fp, "severity": "info", "message": "ruff unavailable; file listed only"})
    return {
        "path": path,
        "issues": issues,
        "issue_count": 0,
        "summary": f"read_lints: {len(files)} file(s); install ruff for diagnostics",
    }


async def export_document(
    section_ids: list[str] | None = None,
    source: str = "current_draft",
    output_path: str = "exports/document.md",
    profile: str | None = None,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    root = Path(settings.workspace_root).resolve()
    export_profile = (profile or settings.writing_export_profile or "novel-zh").strip() or "novel-zh"
    requested = [str(section_id).strip() for section_id in (section_ids or []) if str(section_id).strip()]
    if not requested:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": ["section_ids is required and must not be empty"],
            "included_sections": [],
            "missing_sections": [],
            "source_paths": [],
            "summary": "Export failed: no sections were specified",
        }
    if len(set(requested)) != len(requested):
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": ["section_ids contains duplicates"],
            "included_sections": [],
            "missing_sections": [],
            "source_paths": [],
            "summary": "Export failed: duplicate sections were specified",
        }
    if source not in {"confirmed", "current_draft"}:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [f"unsupported source: {source}"],
            "included_sections": [],
            "missing_sections": requested,
            "source_paths": [],
            "summary": f"Export failed: unsupported source {source!r}",
        }

    manifest = (
        _read_manifest(turn_id, session_id=session_id) if source == "current_draft" else None
    )
    manifest_revisions = manifest.get("revisions", {}) if isinstance(manifest, dict) else {}
    from app.writing.manuscript import (
        confirmed_manuscript_rel,
        draft_manuscript_rel,
        extract_section,
        manuscript_mode,
    )

    sources: list[tuple[str, str, str]] = []  # section_id, rel_path, content
    missing: list[str] = []
    used_legacy_layout = False
    for section_id in requested:
        filename = _section_filename(section_id)
        content: str | None = None
        rel_path = ""

        if source == "confirmed":
            ms_rel = confirmed_manuscript_rel()
            ms_path = _resolve_path(ms_rel)
            if ms_path.is_file():
                extracted = extract_section(
                    ms_path.read_text(encoding="utf-8", errors="replace"), section_id
                )
                if extracted is not None and extracted.strip():
                    content = extracted
                    rel_path = ms_rel
            if content is None:
                rel_path = f"sections/{filename}"
                path = _resolve_path(rel_path)
                if path.is_file():
                    content = path.read_text(encoding="utf-8", errors="replace")
        else:
            candidates: list[str] = []
            manifest_path = manifest_revisions.get(section_id)
            if isinstance(manifest_path, str):
                candidates.append(manifest_path)
            if manuscript_mode() == "monofile" or (
                isinstance(manifest, dict) and manifest.get("layout") == "monofile"
            ):
                draft_ms = draft_manuscript_rel()
                if draft_ms not in candidates:
                    candidates.append(draft_ms)
            for rel in _revision_candidate_paths(
                section_id, session_id=session_id, turn_id=turn_id
            ):
                if rel not in candidates:
                    candidates.append(rel)

            draft_ms_name = Path(draft_manuscript_rel()).name
            for rel in candidates:
                path = _resolve_path(rel)
                if not path.is_file():
                    continue
                raw = path.read_text(encoding="utf-8", errors="replace")
                if Path(rel).name == draft_ms_name or "<!-- section:" in raw:
                    extracted = extract_section(raw, section_id)
                    if extracted is not None and extracted.strip():
                        content = extracted
                        rel_path = rel
                        break
                    continue
                if raw.strip():
                    content = raw
                    rel_path = rel
                    if _is_legacy_revision_rel(rel, filename):
                        used_legacy_layout = True
                    break

        if content is None or not str(content).strip():
            missing.append(section_id)
            continue
        sources.append((section_id, rel_path, content))

    if missing:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [f"missing or empty sections: {', '.join(missing)}"],
            "included_sections": [section_id for section_id, _, _ in sources],
            "missing_sections": missing,
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": f"Export failed: {len(missing)} section(s) missing",
        }

    parts: list[str] = []
    outline = root / "outline.md"
    if outline.is_file():
        parts.append(outline.read_text(encoding="utf-8", errors="replace"))
    for section_id, _, section_body in sources:
        parts.append(f"\n## {section_id}\n\n{section_body.strip()}")
    body = "\n".join(parts).strip()

    from app.writing.export_lint import lint_export_markdown

    lint_issues = lint_export_markdown(body, profile=export_profile, section_ids=requested)
    if lint_issues:
        messages = [f"{issue.code}: {issue.message}" for issue in lint_issues]
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": messages,
            "lint_issues": [{"code": i.code, "message": i.message} for i in lint_issues],
            "included_sections": requested,
            "missing_sections": [],
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": f"Export failed structure lint ({len(lint_issues)} issue(s))",
        }

    from app.privacy.secret_scan import gate_write_content

    blocked = gate_write_content(body, path=output_path)
    if blocked is not None:
        return {
            "output_path": output_path,
            "source": source,
            "profile": export_profile,
            "delivery_status": "failed",
            "delivery_issues": [blocked.get("summary", "secret_scan_blocked")],
            "secret_findings": blocked.get("secret_findings", []),
            "included_sections": requested,
            "missing_sections": [],
            "source_paths": [rel_path for _, rel_path, _ in sources],
            "summary": blocked.get("summary", "Export blocked by secret scan"),
            "status": "blocked",
            "error": "secret_scan_blocked",
        }
    target = _resolve_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    delivery_issues = ["used legacy unscoped revision layout"] if used_legacy_layout else []
    delivery_status = "warning" if delivery_issues else "ok"
    return {
        "output_path": output_path,
        "source": source,
        "profile": export_profile,
        "bytes_written": len(body.encode()),
        "delivery_status": delivery_status,
        "delivery_issues": delivery_issues,
        "included_sections": requested,
        "missing_sections": [],
        "source_paths": [rel_path for _, rel_path, _ in sources],
        "summary": f"Exported {len(requested)} section(s) to {output_path}",
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

