from __future__ import annotations

from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.core.paths import _resolve_path, _workspace_root
from app.tools.core.writing_tools import (
    _is_legacy_revision_rel,
    _read_manifest,
    _revision_candidate_paths,
    _section_filename,
)

async def export_document(
    section_ids: list[str] | None = None,
    source: str = "current_draft",
    output_path: str = "exports/document.md",
    profile: str | None = None,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    # Prefer bound Work root so outline + drafts share the same tree as tools.
    root = _workspace_root()
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
        legacy_draft_manuscript_rel,
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
                legacy_ms = legacy_draft_manuscript_rel()
                if legacy_ms not in candidates:
                    candidates.append(legacy_ms)
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

    # HM7: deterministic citation verify at export boundary (off|warn|block).
    verify_mode = (settings.writing_export_verify_mode or "off").strip().lower()
    cite_issues: list[str] = []
    if verify_mode in {"warn", "block"}:
        from app.controller.verify_pass import scan_text_citations

        cite_issues = scan_text_citations(body)
        if cite_issues and verify_mode == "block":
            return {
                "output_path": output_path,
                "source": source,
                "profile": export_profile,
                "delivery_status": "failed",
                "delivery_issues": cite_issues[:20],
                "included_sections": requested,
                "missing_sections": [],
                "source_paths": [rel_path for _, rel_path, _ in sources],
                "summary": f"Export blocked by citation verify ({len(cite_issues)} issue(s))",
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
    if cite_issues:
        delivery_issues.extend(cite_issues[:10])
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
