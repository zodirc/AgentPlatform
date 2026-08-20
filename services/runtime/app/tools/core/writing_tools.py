from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.settings import settings
from app.tools.core.paths import _resolve_path
from app.writing.hinge import hinge_fields
from app.writing.lore import lore_fields
from app.writing.opening import opening_fields
from app.writing.outline_arc import outline_arc_fields
from app.writing.staccato import staccato_fields
from app.writing.text_metrics import draft_length_fields, outline_thin_fields

_LAST_PLAN_SIG: dict[str, tuple[tuple[str, str, str], ...]] = {}


def _plan_signature(items: list[dict[str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple((row["id"], row["title"], row["status"]) for row in items)

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


# Visible work-surface drafts (tree + double-click). History/turns stay under .agent/.
_WORK_DRAFTS = "drafts"
_LEGACY_WORK_DRAFTS = ".agent/work/drafts"
_WORK_HISTORY = ".agent/work/history"
_WORK_TURNS = ".agent/work/turns"


def _draft_file_path(section_id: str) -> str:
    """Canonical in-progress draft path (work-scoped, not session-scoped)."""
    return f"{_WORK_DRAFTS}/{_section_filename(section_id)}"


def _legacy_draft_file_path(section_id: str) -> str:
    return f"{_LEGACY_WORK_DRAFTS}/{_section_filename(section_id)}"


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
    """Read order: work draft → legacy harness draft → session/turn legacy → flat legacy."""
    filename = _section_filename(section_id)
    paths: list[str] = [_draft_file_path(section_id), _legacy_draft_file_path(section_id)]
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


def _section_drafts_occupied() -> bool:
    from app.writing.occupy import manuscript_is_occupied

    drafts = _resolve_path(_WORK_DRAFTS)
    if not drafts.is_dir():
        return False
    for path in drafts.iterdir():
        if not (path.is_file() and path.suffix == ".md"):
            continue
        try:
            if manuscript_is_occupied(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


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
        legacy_draft_manuscript_rel,
        manuscript_mode,
        upsert_section,
    )

    layout = str(_kwargs.get("layout") or manuscript_mode()).strip().lower()
    if layout not in {"monofile", "sections"}:
        layout = manuscript_mode()

    from app.writing.occupy import (
        archive_occupied_writing_docs,
        manuscript_is_occupied,
        occupy_result_fields,
        should_occupy_fresh,
    )

    manifest = _read_manifest(turn_id, session_id=session_id) or {
        "turn_id": _turn_scope(turn_id),
        "session_id": _session_scope(session_id),
        "sections": [],
        "revisions": {},
        "layout": layout,
    }
    archived: list[str] = []
    occupy_fresh = False

    if layout == "monofile":
        path = draft_manuscript_rel()
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_text(encoding="utf-8")
        else:
            legacy = _resolve_path(legacy_draft_manuscript_rel())
            existing = legacy.read_text(encoding="utf-8") if legacy.is_file() else ""
        occupy_fresh = should_occupy_fresh(
            occupy_arg=_kwargs.get("occupy"),
            user_text=str(_kwargs.get("turn_user_text") or ""),
            already_fresh_this_turn=(
                turn_id is not None and str(manifest.get("occupy") or "") == "fresh"
            ),
            occupied=manuscript_is_occupied(existing),
        )
        if occupy_fresh:
            archived = archive_occupied_writing_docs(layout=layout)
            existing = ""
            manifest["occupy"] = "fresh"
        final = upsert_section(existing, section_id, content)
        target.write_text(final, encoding="utf-8")
    else:
        path = _draft_file_path(section_id)
        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        occupy_fresh = should_occupy_fresh(
            occupy_arg=_kwargs.get("occupy"),
            user_text=str(_kwargs.get("turn_user_text") or ""),
            already_fresh_this_turn=(
                turn_id is not None and str(manifest.get("occupy") or "") == "fresh"
            ),
            occupied=_section_drafts_occupied(),
        )
        if occupy_fresh:
            archived = archive_occupied_writing_docs(layout=layout)
            manifest["occupy"] = "fresh"
        elif not target.exists():
            legacy = _resolve_path(_legacy_draft_file_path(section_id))
            if legacy.is_file():
                target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(content, encoding="utf-8")

    history_path: str | None = None
    keep = int(getattr(settings, "writing_draft_history_keep", 5) or 0)
    if keep > 0 and turn_id is not None:
        history_path = _history_file_path(section_id, turn_id)
        hist = _resolve_path(history_path)
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text(content, encoding="utf-8")
        _prune_section_history(section_id, keep=keep)

    if session_id is not None and not manifest.get("session_id"):
        manifest["session_id"] = _session_scope(session_id)
    manifest["layout"] = layout
    if occupy_fresh and turn_id is not None:
        manifest["occupy"] = "fresh"
        manifest["sections"] = []
        manifest["revisions"] = {}
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
    result.update(
        draft_length_fields(
            content,
            str(_kwargs.get("turn_user_text") or ""),
        )
    )
    result.update(hinge_fields(content))
    result.update(lore_fields(content, section_id))
    result.update(opening_fields(content, section_id))
    result.update(staccato_fields(content))
    if occupy_fresh:
        occupy_fields = occupy_result_fields(archived)
        archive_note = str(occupy_fields.pop("summary", "") or "").strip()
        result.update(occupy_fields)
        if archive_note:
            prev = str(result.get("summary") or "").strip()
            result["summary"] = f"{archive_note} {prev}".strip() if prev else archive_note
    fragment = str(_kwargs.get("fragment") or "mixed").strip()
    try:
        from app.writing.signals.assemble import build_writing_signals

        signals = await build_writing_signals(
            content,
            fragment=fragment,
            section_id=section_id,
            session_id=session_id,
            turn_id=turn_id,
            persist=True,
        )
        result["fragment"] = signals.get("fragment")
        result["writing_signals"] = signals
    except Exception:
        pass
    return result


async def update_plan(
    items: list[dict[str, Any]],
    summary: str = "",
    turn_id=None,
    **_kwargs: Any,
) -> dict[str, Any]:
    plan_id = f"plan-{uuid4().hex[:8]}"
    normalized: list[dict[str, str]] = []
    in_progress_count = 0
    # Planning phase: force all pending so the consent CTA can appear (docs/25).
    force_pending = str(_kwargs.get("plan_phase") or "").strip().lower() == "planning"
    for i, item in enumerate(items):
        status = str(item.get("status", "pending")).strip().lower()
        if force_pending:
            status = "pending"
        elif status in {"done", "complete", "completed"}:
            # Wire value stays `done` for event schema / projector compatibility.
            status = "done"
        elif status in {"in-progress", "running", "in_progress"}:
            status = "in_progress"
            in_progress_count += 1
        elif status in {"cancelled", "canceled", "skipped"}:
            status = "cancelled"
        else:
            status = "pending" if status in {"", "todo", "open", "pending"} else status
        normalized.append(
            {
                "id": str(item.get("id", i + 1)),
                "title": str(item.get("title", item.get("text", "item")))[:512],
                "status": status,
            }
        )
    # Soft discipline: at most one in_progress (keep first; demote extras to pending).
    if in_progress_count > 1 and not force_pending:
        seen = False
        for row in normalized:
            if row["status"] != "in_progress":
                continue
            if not seen:
                seen = True
                continue
            row["status"] = "pending"
    result: dict[str, Any] = {
        "plan_id": plan_id,
        "items": normalized,
        "summary": summary
        or (
            f"Plan with {len(normalized)} item(s) — awaiting confirmation "
            "（请用户点「按此执行」后再开始）"
            if force_pending
            else f"Progress with {len(normalized)} item(s)"
        ),
    }
    if force_pending:
        result["plan_phase"] = "planning"
        result["awaiting_consent"] = True
        if summary:
            result["summary"] = summary
    sig = _plan_signature(normalized)
    key = str(turn_id) if turn_id is not None else ""
    if key and _LAST_PLAN_SIG.get(key) == sig:
        result["unchanged"] = True
        result["summary"] = "Plan unchanged"
        return result
    if key:
        if len(_LAST_PLAN_SIG) > 256:
            _LAST_PLAN_SIG.clear()
        _LAST_PLAN_SIG[key] = sig
    return result


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

    from app.writing.occupy import (
        archive_occupied_writing_docs,
        manuscript_is_occupied,
        occupy_result_fields,
        should_occupy_fresh,
    )

    turn_id = _kwargs.get("turn_id")
    session_id = _kwargs.get("session_id")
    manifest = _read_manifest(turn_id, session_id=session_id) or {}

    occupy_fresh = should_occupy_fresh(
        occupy_arg=_kwargs.get("occupy"),
        user_text=str(_kwargs.get("turn_user_text") or ""),
        already_fresh_this_turn=(
            turn_id is not None and str(manifest.get("occupy") or "") == "fresh"
        ),
        occupied=manuscript_is_occupied(existing),
    )
    archived: list[str] = []
    if occupy_fresh:
        archived = archive_occupied_writing_docs(layout="monofile")
        existing = ""
        mode_n = "replace"
        force = True
        if turn_id is not None:
            manifest = {
                "turn_id": _turn_scope(turn_id),
                "session_id": _session_scope(session_id),
                "sections": list(manifest.get("sections") or []),
                "revisions": dict(manifest.get("revisions") or {}),
                "layout": str(manifest.get("layout") or "monofile"),
                "occupy": "fresh",
            }
            _write_manifest(turn_id, manifest, session_id=session_id)

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
                "path": path,
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
    scored = content if mode_n == "append" else final
    result: dict[str, Any] = {
        "path": path,
        "content": final,
        "summary": summary,
        "outline_path": path,
        "mode": "append" if mode_n == "append" else "replace",
    }
    thin = outline_thin_fields(scored, str(_kwargs.get("turn_user_text") or ""))
    suffix = thin.pop("summary_suffix", None)
    result.update(thin)
    arc = outline_arc_fields(final, str(_kwargs.get("turn_user_text") or ""))
    arc_suffix = arc.pop("summary_suffix", None)
    result.update(arc)
    notes = [part for part in (suffix, arc_suffix) if part]
    if occupy_fresh:
        occupy_fields = occupy_result_fields(archived)
        archive_note = str(occupy_fields.pop("summary", "") or "").strip()
        result.update(occupy_fields)
        if archive_note:
            notes.insert(0, archive_note)
    if notes:
        result["summary"] = f"{summary}；" + "；".join(notes)
    return result
