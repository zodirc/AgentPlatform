from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.settings import settings

_CITE_RE = re.compile(r"\bcite:([A-Za-z0-9_./\-]+)\b")
_REF_PATH_RE = re.compile(r"(?:sources|sections)/[A-Za-z0-9_./\-]+\.(?:md|txt|markdown)\b")


def _workspace() -> Path:
    return Path(settings.workspace_root).resolve()


def _iter_draft_texts(root: Path) -> list[tuple[str, str]]:
    candidates: list[Path] = []
    for rel in ("exports", "sections", ".agent/revisions"):
        base = root / rel
        if base.is_dir():
            candidates.extend(p for p in base.rglob("*.md") if p.is_file())
    texts: list[tuple[str, str]] = []
    for path in sorted(candidates)[:80]:
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
    if not sources.is_dir():
        return False
    for fp in sources.rglob("*"):
        if not fp.is_file():
            continue
        name = fp.name
        if stem in name or stem in str(fp.relative_to(root)):
            return True
        try:
            if stem and stem in fp.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def run_verify_pass(*, session_id: str | None = None) -> dict[str, Any]:
    """Deterministic citation verify (docs/17 S3 A4) — user/offline only, no draft mutation."""
    root = _workspace()
    findings: list[dict[str, Any]] = []
    checked = 0
    for rel, text in _iter_draft_texts(root):
        cites = sorted(set(_CITE_RE.findall(text)))
        paths = sorted(set(_REF_PATH_RE.findall(text)))
        for cite in cites:
            checked += 1
            ok = _source_exists(root, cite)
            findings.append(
                {
                    "file": rel,
                    "citation_id": f"cite:{cite}" if not cite.startswith("cite:") else cite,
                    "valid": ok,
                }
            )
        for path in paths:
            checked += 1
            ok = (root / path).is_file()
            findings.append({"file": rel, "path": path, "valid": ok})

    invalid = [f for f in findings if not f.get("valid")]
    lines = [
        f"# Verify report",
        f"",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- session_id: {session_id or '-'}",
        f"- checked: {checked}",
        f"- invalid: {len(invalid)}",
        f"",
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
