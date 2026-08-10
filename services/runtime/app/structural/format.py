from __future__ import annotations

import re
from collections import defaultdict

from app.structural.types import Issue, Location

_RUFF_LINE_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+):\s+(?P<code>[A-Z]\d+)\s+(?P<msg>.+)$"
)


def lsp_severity_to_str(value: int | None) -> str:
    # LSP DiagnosticSeverity: 1 Error, 2 Warning, 3 Information, 4 Hint
    if value == 1:
        return "error"
    if value == 2:
        return "warning"
    if value in {3, 4}:
        return "info"
    return "warning"


def ruff_code_severity(code: str) -> str:
    if not code:
        return "warning"
    head = code[0].upper()
    if head in {"E", "F"}:
        return "error"
    if head == "W":
        return "warning"
    if head == "I":
        return "info"
    return "warning"


def parse_ruff_concise_line(line: str, *, default_path: str = ".") -> Issue | None:
    text = line.strip()
    if not text:
        return None
    match = _RUFF_LINE_RE.match(text)
    if match:
        code = match.group("code")
        return Issue(
            path=match.group("path"),
            line=int(match.group("line")),
            col=int(match.group("col")),
            severity=ruff_code_severity(code),
            message=match.group("msg").strip(),
            provider="ruff",
            code=code,
            sources=("ruff",),
        )
    return Issue(
        path=default_path,
        line=1,
        col=1,
        severity="warning",
        message=text,
        provider="ruff",
        sources=("ruff",),
    )


def _dedupe_key(issue: Issue) -> tuple[str, int, str]:
    normalized = (issue.code or issue.message).strip().lower()
    return (issue.path.replace("\\", "/"), issue.line, normalized)


def merge_issues(*groups: list[Issue]) -> list[Issue]:
    """Merge LSP ∪ CLI issues; prefer richer (typed LSP) when keys collide."""
    best: dict[tuple[str, int, str], Issue] = {}
    for group in groups:
        for issue in group:
            key = _dedupe_key(issue)
            existing = best.get(key)
            if existing is None:
                best[key] = issue
                continue
            sources = tuple(dict.fromkeys([*existing.sources, *issue.sources, existing.provider, issue.provider]))
            # Prefer LSP when it carries a code or longer message (type info).
            prefer_new = False
            if issue.provider == "lsp" and existing.provider != "lsp":
                prefer_new = True
            elif len(issue.message) > len(existing.message) and issue.provider == "lsp":
                prefer_new = True
            chosen = issue if prefer_new else existing
            other = existing if prefer_new else issue
            best[key] = Issue(
                path=chosen.path,
                line=chosen.line,
                col=chosen.col,
                severity=chosen.severity,
                message=chosen.message,
                provider=chosen.provider,
                code=chosen.code or other.code,
                sources=sources,
            )
    return sorted(best.values(), key=lambda i: (i.path, i.line, i.col, i.code, i.message))


def format_diagnostics_lines(issues: list[Issue], *, limit: int = 200) -> list[str]:
    lines: list[str] = []
    for issue in issues[:limit]:
        code = issue.code or "diag"
        providers = "+".join(issue.sources) if issue.sources else issue.provider
        lines.append(
            f"{issue.path}:{issue.line}:{issue.col} {issue.severity} "
            f"[{providers}:{code}] {issue.message}"
        )
    return lines


def format_locations_lines(locations: list[Location], *, limit: int = 200) -> list[str]:
    lines: list[str] = []
    for loc in locations[:limit]:
        snippet = (loc.snippet or "").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        base = f"{loc.path}:{loc.line}:{loc.col} {loc.kind} {loc.symbol}"
        lines.append(f"{base} | {snippet}" if snippet else base)
    return lines


def aggregate_refs_by_file(
    locations: list[Location],
    *,
    max_refs: int,
) -> tuple[list[Location], list[str], bool]:
    """Cap references; overflow becomes per-file pointers."""
    if len(locations) <= max_refs:
        return locations, [], False
    kept = locations[:max_refs]
    rest = locations[max_refs:]
    counts: dict[str, int] = defaultdict(int)
    for loc in rest:
        counts[loc.path] += 1
    pointers = [f"{path} ({n} more hits)" for path, n in sorted(counts.items())]
    return kept, pointers, True
