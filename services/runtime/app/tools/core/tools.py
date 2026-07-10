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


def _manifest_path(turn_id: object | None) -> str:
    return f".agent/turns/{_turn_scope(turn_id)}/manifest.json"


def _read_manifest(turn_id: object | None) -> dict[str, Any] | None:
    target = _resolve_path(_manifest_path(turn_id))
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_manifest(turn_id: object | None, manifest: dict[str, Any]) -> str:
    path = _manifest_path(turn_id)
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
    **_kwargs: Any,
) -> dict[str, Any]:
    filename = _section_filename(section_id)
    path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    manifest = _read_manifest(turn_id) or {
        "turn_id": _turn_scope(turn_id),
        "sections": [],
        "revisions": {},
    }
    sections = manifest.setdefault("sections", [])
    revisions = manifest.setdefault("revisions", {})
    if section_id not in sections:
        sections.append(section_id)
    revisions[section_id] = path
    manifest_path = _write_manifest(turn_id, manifest)
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

    from app.retrieval.vector_index import SourceVectorIndex

    sources = _resolve_path("sources")
    workspace_root = Path(settings.workspace_root).resolve()
    if not sources.exists():
        return {"indexed_files": 0, "chunks": 0, "added": 0, "updated": 0}
    index_path = Path(settings.data_dir) / "vectorstore" / "sources.json"
    index = SourceVectorIndex(index_path)
    return index.sync(sources, workspace_root=workspace_root)


async def search_sources(query: str, limit: int = 10, **_kwargs: Any) -> dict[str, Any]:
    from pathlib import Path

    from app.retrieval.vector_index import SourceVectorIndex

    sources = _resolve_path("sources")
    if not sources.exists():
        return {"query": query, "hits": [], "summary": "No sources directory", "retrieval": "none"}

    mode = settings.retrieval_mode.lower()
    workspace_root = Path(settings.workspace_root).resolve()

    if mode in {"vector", "hybrid"}:
        index_path = Path(settings.data_dir) / "vectorstore" / "sources.json"
        index = SourceVectorIndex(index_path)
        sync_stats: dict[str, Any] = {"skipped": True}
        try:
            if not settings.index_via_worker:
                sync_stats = index.sync(sources, workspace_root=workspace_root)
                vector_hits = index.search(query, limit=limit)
            else:
                index.load()
                vector_hits = index.search(query, limit=limit)
                if not vector_hits:
                    sync_stats = index.sync(sources, workspace_root=workspace_root)
                    vector_hits = index.search(query, limit=limit)
        except OSError:
            sync_stats = {"error": "vector_index_unavailable"}
            vector_hits = []
        if vector_hits or mode == "vector":
            hits = [
                {
                    "path": hit.path,
                    "chunk_id": hit.chunk_id,
                    "excerpt": hit.excerpt,
                    "citation_id": hit.citation_id,
                    "score": round(hit.score, 4),
                }
                for hit in vector_hits
            ]
            return {
                "query": query,
                "hits": hits,
                "summary": f"search_sources(vector): {len(hits)} hit(s)",
                "retrieval": "vector",
                "index": sync_stats,
            }

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    hits: list[dict[str, Any]] = []
    for fp in sorted(sources.rglob("*")):
        if not fp.is_file():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if terms and not all(t.lower() in lowered for t in terms):
            continue
        rel = str(fp.relative_to(workspace_root))
        excerpt = text[:400].strip()
        hits.append({"path": rel, "excerpt": excerpt, "citation_id": f"cite:{fp.stem}"})
        if len(hits) >= limit:
            break
    return {
        "query": query,
        "hits": hits,
        "summary": f"search_sources(keyword): {len(hits)} hit(s)",
        "retrieval": "keyword",
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
    turn_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    root = Path(settings.workspace_root).resolve()
    requested = [str(section_id).strip() for section_id in (section_ids or []) if str(section_id).strip()]
    if not requested:
        return {
            "output_path": output_path,
            "source": source,
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
            "delivery_status": "failed",
            "delivery_issues": [f"unsupported source: {source}"],
            "included_sections": [],
            "missing_sections": requested,
            "source_paths": [],
            "summary": f"Export failed: unsupported source {source!r}",
        }

    manifest = _read_manifest(turn_id) if source == "current_draft" else None
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
            scoped_path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
            if all(rel != scoped_path for rel, _ in candidates):
                candidates.append((scoped_path, _resolve_path(scoped_path)))
            # Read compatibility for drafts created before revisions became turn-scoped.
            legacy_path = f".agent/revisions/{filename}"
            candidates.append((legacy_path, _resolve_path(legacy_path)))

        selected = next(((rel, path) for rel, path in candidates if path.is_file()), None)
        if selected is None:
            missing.append(section_id)
            continue
        rel_path, path = selected
        if rel_path == f".agent/revisions/{filename}":
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
    target = _resolve_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    delivery_issues = ["used legacy unscoped revision layout"] if used_legacy_layout else []
    delivery_status = "warning" if delivery_issues else "ok"
    return {
        "output_path": output_path,
        "source": source,
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
    **_kwargs: Any,
) -> dict[str, Any]:
    from app.tools.delegate_runner import run_delegate

    return await run_delegate(task=task, agent_type=agent_type, context=context, **_kwargs)

