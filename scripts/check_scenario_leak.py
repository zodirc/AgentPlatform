#!/usr/bin/env python3
"""Scenario constitution leak scanner.

Scans non-test Python under ``services/runtime/app`` and ``services/api/app``
for hard-coded scenario-name branches. Known stock leaks live in
``scripts/scenario_leak_allowlist.txt`` (path:lineno). New hits fail; stale
allowlist entries fail. Prefer Profile/hooks — docs/core/architecture.md §4.1.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "scenario_leak_allowlist.txt"
SCAN_ROOTS = (
    ROOT / "services" / "runtime" / "app",
    ROOT / "services" / "api" / "app",
)
SCENARIO_IDS = ("writing", "agent", "collab", "intel")
_IDS = "|".join(SCENARIO_IDS)

# scenario_id / state.scenario_id / ctx.scenario_id compared to a literal id.
# Also covers ``(scenario_id or "").strip() == "writing"`` and plan_suggest
# ``key == "agent"`` (L12 inventory).
LEAK_RE = re.compile(
    rf"""
    (?:
        \(?\s*(?:\w+\.)?scenario_id
        (?:\s*or\s*[^)\n]+)?
        \)?
        (?:\s*\.\s*strip\s*\(\s*\))?
        \s*(?:==|!=)\s*["'](?:{_IDS})["']
    )
    |
    (?:
        ["'](?:{_IDS})["']\s*(?:==|!=)\s*(?:\w+\.)?scenario_id
    )
    |
    (?:
        \bkey\s*==\s*["'](?:{_IDS})["']
    )
    """,
    re.VERBOSE,
)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_allowlist(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.is_file():
        raise SystemExit(f"missing allowlist: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # path:lineno
        if ":" not in line:
            raise SystemExit(f"bad allowlist line (want path:lineno): {raw!r}")
        rel, _, rest = line.partition(":")
        lineno = rest.split()[0] if rest.strip() else ""
        if not rel or not lineno.isdigit():
            raise SystemExit(f"bad allowlist line (want path:lineno): {raw!r}")
        out.add(f"{rel}:{int(lineno)}")
    return out


def iter_py_files(scan_roots: tuple[Path, ...] | None = None) -> list[Path]:
    files: list[Path] = []
    for base in scan_roots or SCAN_ROOTS:
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "tests" in path.parts or "test" in path.parts:
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                continue
            files.append(path)
    return sorted(files)


def find_leaks(
    scan_roots: tuple[Path, ...] | None = None,
) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in iter_py_files(scan_roots):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = _rel(path)
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if LEAK_RE.search(line):
                hits.append((rel, i, stripped))
    return hits


def check(
    *,
    allowlist: set[str],
    scan_roots: tuple[Path, ...] | None = None,
) -> list[str]:
    errors: list[str] = []
    found_keys: set[str] = set()
    for rel, lineno, snippet in find_leaks(scan_roots):
        key = f"{rel}:{lineno}"
        found_keys.add(key)
        if key not in allowlist:
            errors.append(
                f"NEW leak {key}: {snippet}  "
                f"(migrate to Profile/hooks — docs/core/architecture.md §4.1)"
            )
    for key in sorted(allowlist - found_keys):
        errors.append(
            f"STALE allowlist {key}: no matching leak at that line "
            f"(remove after fix, or refresh lineno if the branch moved)"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=ALLOWLIST_PATH,
        help="path to scenario leak allowlist",
    )
    parser.add_argument(
        "--print-hits",
        action="store_true",
        help="print all hits and exit 0 (no allowlist gate)",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        type=Path,
        default=None,
        help="override scan roots (repeatable; tests inject a synthetic leak tree)",
    )
    args = parser.parse_args(argv)
    scan_roots = tuple(args.scan_root) if args.scan_root else None

    if args.print_hits:
        for rel, lineno, snippet in find_leaks(scan_roots):
            print(f"{rel}:{lineno}:{snippet}")
        return 0

    allowlist = load_allowlist(args.allowlist)
    errors = check(allowlist=allowlist, scan_roots=scan_roots)
    if errors:
        print("Scenario leak gate FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"Scenario leak gate OK ({len(allowlist)} allowlisted stock leaks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
