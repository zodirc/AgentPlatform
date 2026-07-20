from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.settings import settings
from app.tools.validate import extract_citation_ids

_REF_PATH_RE_IMPORT = None


def _ref_path_re():
    import re

    global _REF_PATH_RE_IMPORT
    if _REF_PATH_RE_IMPORT is None:
        # Paths may include CJK filenames.
        _REF_PATH_RE_IMPORT = re.compile(
            r"(?:sources|sections)/[^\s\]\[<>\"'`，。；;]+\.(?:md|txt|markdown)\b"
        )
    return _REF_PATH_RE_IMPORT


def _workspace() -> Path:
    return Path(settings.workspace_root).resolve()


def _iter_draft_texts(root: Path) -> list[tuple[str, str]]:
    candidates: list[Path] = []
    for rel in ("exports", "sections"):
        base = root / rel
        if base.is_dir():
            candidates.extend(p for p in base.rglob("*.md") if p.is_file())
    sessions = root / ".agent" / "sessions"
    if sessions.is_dir():
        candidates.extend(
            p
            for p in sessions.rglob("*.md")
            if p.is_file() and "revisions" in p.relative_to(sessions).parts
        )
    legacy_revisions = root / ".agent" / "revisions"
    if legacy_revisions.is_dir():
        candidates.extend(p for p in legacy_revisions.rglob("*.md") if p.is_file())
    # Prefer recently modified drafts so verify hits the latest writing turn.
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    texts: list[tuple[str, str]] = []
    for path in candidates[:120]:
        try:
            texts.append(
                (
                    str(path.relative_to(root)),
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            )
        except OSError:
            continue
    return texts


def _source_exists(root: Path, citation_id: str) -> bool:
    stem = citation_id.replace("cite:", "").strip()
    sources = root / "sources"
    if not sources.is_dir() or not stem:
        return False
    for fp in sources.rglob("*"):
        if not fp.is_file():
            continue
        name = fp.name
        if stem in name or stem in str(fp.relative_to(root)):
            return True
        # Also accept stem without extension match (亮剑 ↔ 亮剑.md).
        if fp.stem == stem:
            return True
        try:
            if stem in fp.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def run_verify_pass(*, session_id: str | None = None) -> dict[str, Any]:
    """Deterministic citation verify (docs/13 S3 A4) — user/offline only, no draft mutation."""
    root = _workspace()
    findings: list[dict[str, Any]] = []
    checked = 0
    path_re = _ref_path_re()
    for rel, text in _iter_draft_texts(root):
        cites = extract_citation_ids(text)
        paths = sorted(set(path_re.findall(text)))
        for cite in cites:
            checked += 1
            ok = _source_exists(root, cite)
            findings.append(
                {
                    "file": rel,
                    "citation_id": cite if cite.startswith("cite:") else f"cite:{cite}",
                    "valid": ok,
                }
            )
        for path in paths:
            checked += 1
            ok = (root / path).is_file()
            findings.append({"file": rel, "path": path, "valid": ok})

    invalid = [f for f in findings if not f.get("valid")]
    lines = [
        "# Verify report",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- session_id: {session_id or '-'}",
        f"- checked: {checked}",
        f"- invalid: {len(invalid)}",
        "",
    ]
    if invalid:
        lines.append("## Issues")
        for item in invalid[:50]:
            lines.append(f"- `{item}`")
        lines.append("")
    else:
        lines.append("No citation/path issues found in drafts/exports.")
        lines.append("")

    report_dir = root / ".agent" / "verify-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"verify-{stamp}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    rel_report = str(report_path.relative_to(root))
    summary = (
        f"Verify complete: checked={checked}, invalid={len(invalid)}; "
        f"report={rel_report}"
    )
    return {
        "status": "completed",
        "checked": checked,
        "invalid": len(invalid),
        "findings": findings[:100],
        "report_path": rel_report,
        "summary": summary,
        "mutated_draft": False,
    }
