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


async def read_file(path: str, **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(path)
    if not target.exists():
        return {"error": f"File not found: {path}"}
    if not target.is_file():
        return {"error": f"Not a file: {path}"}
    content = target.read_text(encoding="utf-8", errors="replace")
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
    patch_id = f"patch-{uuid4().hex[:12]}"
    return {
        "patch_id": patch_id,
        "path": path,
        "old_text": old_text,
        "new_text": new_text,
        "summary": summary or f"Proposed changes to {path}",
        "status": "pending",
    }


async def apply_patch(path: str, new_text: str, **_kwargs: Any) -> dict[str, Any]:
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_text, encoding="utf-8")
    return {"path": path, "status": "applied", "bytes_written": len(new_text.encode())}


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


def _manifest_path(session_id: object | None, turn_id: object | None) -> str:
    """Primary manifest path (session-scoped when session_id is known)."""
    if session_id is not None and turn_id is not None:
        return (
            f".agent/sessions/{_session_scope(session_id)}/turns/"
            f"{_turn_scope(turn_id)}/manifest.json"
        )
    return f".agent/turns/{_turn_scope(turn_id)}/manifest.json"


def _manifest_candidate_paths(session_id: object | None, turn_id: object | None) -> list[str]:
    paths: list[str] = []
    if session_id is not None and turn_id is not None:
        paths.append(_manifest_path(session_id, turn_id))
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
    filename = _section_filename(section_id)
    if session_id is not None and turn_id is not None:
        return (
            f".agent/sessions/{_session_scope(session_id)}/revisions/"
            f"{_turn_scope(turn_id)}/{filename}"
        )
    return f".agent/revisions/{_turn_scope(turn_id)}/{filename}"


def _revision_candidate_paths(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> list[str]:
    """Read order: manifest entry → session path → turn path → flat legacy."""
    filename = _section_filename(section_id)
    paths: list[str] = []
    if session_id is not None and turn_id is not None:
        paths.append(_revision_file_path(section_id, session_id=session_id, turn_id=turn_id))
    if turn_id is not None:
        turn_path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
        if turn_path not in paths:
            paths.append(turn_path)
    legacy_flat = f".agent/revisions/{filename}"
    if legacy_flat not in paths:
        paths.append(legacy_flat)
    return paths


def _is_legacy_revision_rel(rel_path: str, filename: str) -> bool:
    """True only for pre-turn-scoped flat revision files."""
    return rel_path == f".agent/revisions/{filename}"


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
    path = _revision_file_path(section_id, session_id=session_id, turn_id=turn_id)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    manifest = _read_manifest(turn_id, session_id=session_id) or {
        "turn_id": _turn_scope(turn_id),
        "session_id": _session_scope(session_id),
        "sections": [],
        "revisions": {},
    }
    if session_id is not None and not manifest.get("session_id"):
        manifest["session_id"] = _session_scope(session_id)
    sections = manifest.setdefault("sections", [])
    revisions = manifest.setdefault("revisions", {})
    if section_id not in sections:
        sections.append(section_id)
    revisions[section_id] = path
    manifest_path = _write_manifest(turn_id, manifest, session_id=session_id)
    return {
        "section_id": section_id,
        "path": path,
        "manifest_path": manifest_path,
        "status": "drafted",
    }


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


async def update_outline(content: str, **_kwargs: Any) -> dict[str, Any]:
    path = "outline.md"
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "path": path,
        "content": content,
        "summary": "Outline updated",
        "outline_path": path,
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
    from pathlib import Path

    from app.retrieval.store import get_sources_store

    sources = _resolve_path("sources")
    workspace_root = Path(settings.workspace_root).resolve()
    if not sources.exists():
        return {"indexed_files": 0, "chunks": 0, "added": 0, "updated": 0}
    store = get_sources_store()
    return store.sync(sources, workspace_root=workspace_root)


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
) -> list[dict[str, Any]]:
    from app.retrieval.chunking import should_index_source

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    hits: list[dict[str, Any]] = []
    excerpt_chars = settings.search_sources_excerpt_chars
    for fp in sorted(sources.rglob("*")):
        if not fp.is_file() or not should_index_source(fp):
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if terms and not all(t.lower() in lowered for t in terms):
            continue
        rel = str(fp.relative_to(workspace_root))
        excerpt = text[:excerpt_chars].strip()
        if len(text) > excerpt_chars:
            excerpt += "…"
        hits.append({"path": rel, "excerpt": excerpt, "citation_id": f"cite:{fp.stem}"})
        if len(hits) >= limit:
            break
    return hits


async def search_sources(query: str, limit: int = 10, **_kwargs: Any) -> dict[str, Any]:
    from pathlib import Path

    from app.retrieval.store import get_sources_store

    sources = _resolve_path("sources")
    if not sources.exists():
        return {"query": query, "hits": [], "summary": "No sources directory", "retrieval": "none"}

    mode = settings.retrieval_mode.lower()
    workspace_root = Path(settings.workspace_root).resolve()
    excerpt_chars = settings.search_sources_excerpt_chars

    if mode == "keyword":
        hits = _search_sources_keyword(
            sources, workspace_root=workspace_root, query=query, limit=limit
        )
        return {
            "query": query,
            "hits": hits,
            "summary": f"search_sources(keyword): {len(hits)} hit(s)",
            "retrieval": "keyword",
        }

    # Hot path: load + search only. Never store.sync() here (A9 / docs/17 S2).
    store = get_sources_store()
    index_meta: dict[str, Any] = {
        "synced_on_query": False,
        "index_via_worker": settings.index_via_worker,
    }
    try:
        store.load()
        raw_hits = store.search(query, limit=limit, mode=mode)
        retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"
    except OSError:
        index_meta["error"] = "vector_index_unavailable"
        raw_hits = []
        retrieval = mode if mode in {"vector", "hybrid"} else "hybrid"

    if raw_hits:
        hits = _format_source_hits(raw_hits, excerpt_chars=excerpt_chars)
        payload: dict[str, Any] = {
            "query": query,
            "hits": hits,
            "summary": f"search_sources({retrieval}): {len(hits)} hit(s)",
            "retrieval": retrieval,
            "index": index_meta,
        }
        if hits and hits[0].get("score", 0.0) < settings.search_sources_low_score_hint:
            top_path = hits[0].get("path", "")
            payload["hint"] = (
                "Low relevance scores; prefer read_file on the top path "
                f"({top_path}) instead of repeating search_sources."
            )
        return payload

    # Empty/stale index: keyword filesystem scan (no rebuild), plus lag hint.
    index_meta["index_lag"] = True
    index_meta["hint"] = (
        "Vector index empty or lagging; search used keyword fallback. "
        "Rebuild via sync_sources_index / worker upload path — not on query."
    )
    hits = _search_sources_keyword(sources, workspace_root=workspace_root, query=query, limit=limit)
    return {
        "query": query,
        "hits": hits,
        "summary": f"search_sources(keyword-fallback): {len(hits)} hit(s)",
        "retrieval": "keyword",
        "index": index_meta,
        "hint": index_meta["hint"],
    }


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
    sources: list[tuple[str, str, Path]] = []
    missing: list[str] = []
    used_legacy_layout = False
    for section_id in requested:
        filename = _section_filename(section_id)
        candidates: list[tuple[str, Path]] = []
        if source == "confirmed":
            rel_path = f"sections/{filename}"
            candidates.append((rel_path, _resolve_path(rel_path)))
        else:
            manifest_path = manifest_revisions.get(section_id)
            if isinstance(manifest_path, str):
                candidates.append((manifest_path, _resolve_path(manifest_path)))
            for rel in _revision_candidate_paths(
                section_id, session_id=session_id, turn_id=turn_id
            ):
                if all(rel != existing for existing, _ in candidates):
                    candidates.append((rel, _resolve_path(rel)))

        selected = next(((rel, path) for rel, path in candidates if path.is_file()), None)
        if selected is None:
            missing.append(section_id)
            continue
        rel_path, path = selected
        if _is_legacy_revision_rel(rel_path, filename):
            used_legacy_layout = True
        content = path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            missing.append(section_id)
            continue
        sources.append((section_id, rel_path, path))

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
    for section_id, _, path in sources:
        parts.append(
            f"\n## {section_id}\n\n{path.read_text(encoding='utf-8', errors='replace').strip()}"
        )
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

