from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*)$", re.M)
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
SECTION_SPLIT_RE = re.compile(r"(?m)^(#{1,6}\s+\S.*)$")


@dataclass(frozen=True)
class ExportLintIssue:
    code: str
    message: str


def lint_export_markdown(
    body: str,
    *,
    profile: str = "novel-zh",
    section_ids: list[str] | None = None,
) -> list[ExportLintIssue]:
    """Deterministic markdown structure checks before export write (docs/14 D6)."""
    issues: list[ExportLintIssue] = []
    text = body.strip()
    if not text:
        issues.append(ExportLintIssue("empty_document", "export body is empty"))
        return issues

    headings = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(text)]
    if not headings:
        issues.append(ExportLintIssue("no_headings", "document has no markdown headings"))

    prev_level: int | None = None
    for _, level, title in headings:
        if prev_level is not None and level > prev_level + 1:
            issues.append(
                ExportLintIssue(
                    "heading_skip",
                    f"heading level jumps from h{prev_level} to h{level} near {title!r}",
                )
            )
        prev_level = level

    # Empty sections: only flag ##+ headings (outline H1 may be title-only).
    # When section_ids provided, only those ## markers must be non-empty.
    parts = SECTION_SPLIT_RE.split(text)
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            heading = parts[i].strip()
            body_part = parts[i + 1] if i + 1 < len(parts) else ""
            level = len(heading) - len(heading.lstrip("#"))
            title = heading.lstrip("#").strip()
            if level < 2:
                continue
            if section_ids is not None and title not in section_ids:
                continue
            if not body_part.strip():
                issues.append(
                    ExportLintIssue(
                        "empty_section",
                        f"empty section under {heading!r}",
                    )
                )

    if section_ids:
        missing_ids = [sid for sid in section_ids if sid not in text]
        if missing_ids:
            issues.append(
                ExportLintIssue(
                    "section_ids_missing_in_body",
                    f"assembled body missing section markers: {', '.join(missing_ids)}",
                )
            )

    if profile in {"novel-zh", "essay"}:
        if HTML_TAG_RE.search(text):
            issues.append(ExportLintIssue("html_forbidden", f"profile {profile} forbids raw HTML tags"))

    return issues
