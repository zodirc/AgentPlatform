#!/usr/bin/env python3
"""LOC ratchet gate.

Non-test ``.py`` / ``.ts`` / ``.tsx`` under ``services/`` must stay ≤ HARD_CAP
unless listed in ``scripts/loc_allowlist.txt``.

Allowlist entries are **budgets** (round ceilings), not the file's current LOC.
Allowlisted files may not grow above ``budget + TOLERANCE``. Once a file drops
≤ HARD_CAP, remove its allowlist entry. Prefer splitting new modules over adding
allowlist rows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "loc_allowlist.txt"
# p95 of services/ sources sits near 800 — keep this as the default hard top.
HARD_CAP = 800
# Headroom on allowlisted budgets so small feature PRs do not thrash the allowlist.
TOLERANCE = 100
SCAN_ROOT = ROOT / "services"
SUFFIXES = {".py", ".ts", ".tsx"}
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    "tests",
    "test",
    "coverage",
    "htmlcov",
}


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _physical_lines(path: Path) -> int:
    # Count like ``wc -l`` (newline-terminated); empty file → 0.
    data = path.read_bytes()
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def load_allowlist(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not path.is_file():
        raise SystemExit(f"missing allowlist: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            rel, max_s = line.split("\t", 1)
        else:
            parts = line.split()
            if len(parts) != 2:
                raise SystemExit(f"bad allowlist line: {raw!r}")
            rel, max_s = parts
        out[rel.strip()] = int(max_s.strip())
    return out


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    if not SCAN_ROOT.is_dir():
        return files
    for path in SCAN_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in SUFFIXES:
            continue
        # Generated / declaration files are not hand-maintained modules.
        if path.name.endswith(".d.ts"):
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        name = path.name
        if ".test." in name or ".spec." in name or name.endswith("_test.py"):
            continue
        files.append(path)
    return sorted(files)


def check(*, allowlist: dict[str, int]) -> list[str]:
    errors: list[str] = []
    seen_allow: set[str] = set()
    for path in iter_source_files():
        rel = _rel(path)
        n = _physical_lines(path)
        if rel in allowlist:
            seen_allow.add(rel)
            cap = allowlist[rel]
            if n <= HARD_CAP:
                errors.append(
                    f"{rel}: {n} lines ≤ {HARD_CAP} — remove from loc_allowlist.txt "
                    f"(was capped at {cap})"
                )
            elif n > cap + TOLERANCE:
                errors.append(
                    f"{rel}: grew to {n} lines (allowlist budget {cap}, "
                    f"tolerance +{TOLERANCE}). Split the module or raise the budget."
                )
            continue
        if n > HARD_CAP:
            errors.append(
                f"{rel}: {n} lines > {HARD_CAP} and not in loc_allowlist.txt. "
                f"Split the module or (legacy only) add a budget entry."
            )
    for rel, cap in sorted(allowlist.items()):
        if rel in seen_allow:
            continue
        target = ROOT / rel
        if not target.is_file():
            errors.append(f"{rel}: allowlist entry missing on disk (was max {cap})")
        else:
            # Skipped by filters (e.g. moved under tests/) — still stale.
            errors.append(
                f"{rel}: allowlisted but not scanned (moved/renamed? was max {cap})"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=ALLOWLIST_PATH,
        help="path to loc allowlist",
    )
    parser.add_argument(
        "--print-over",
        action="store_true",
        help="list files over HARD_CAP and exit 0 (no ratchet)",
    )
    args = parser.parse_args(argv)

    if args.print_over:
        for path in iter_source_files():
            n = _physical_lines(path)
            if n > HARD_CAP:
                print(f"{n}\t{_rel(path)}")
        return 0

    allowlist = load_allowlist(args.allowlist)
    errors = check(allowlist=allowlist)
    if errors:
        print("LOC ratchet FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(
        f"LOC ratchet OK ({len(allowlist)} allowlisted; hard cap {HARD_CAP}; "
        f"tolerance +{TOLERANCE})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
