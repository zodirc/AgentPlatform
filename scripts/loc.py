#!/usr/bin/env python3
"""Count project source lines (no deps, no docs, no workspace content).

Usage:
  python scripts/loc.py
  python scripts/loc.py --by-file
  make loc
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# First-party trees only.
DEFAULT_ROOTS = ("services", "packages", "eval", "scripts")

CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".css",
    ".sql",
    ".sh",
}

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
    "coverage",
    ".turbo",
    ".next",
    "egg-info",
}

SKIP_PATH_PREFIXES = (
    "docs/",
    "workspace/",
    "seed/",
    ".eval-workspace/",
    "eval/reports/",
)

SKIP_NAME_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

SKIP_FILE_NAMES = {
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "uv.lock",
    "poetry.lock",
}


@dataclass(frozen=True)
class FileStat:
    path: Path
    physical: int
    code: int
    blank: int
    comment: int


def _is_skipped_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES or name.endswith(".egg-info")


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _should_skip_file(path: Path) -> bool:
    rel = _rel(path)
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in SKIP_PATH_PREFIXES):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    lower = path.name.lower()
    if any(lower.endswith(suf) for suf in SKIP_NAME_SUFFIXES):
        return True
    if path.suffix.lower() not in CODE_SUFFIXES:
        return True
    return False


def _iter_code_files(roots: list[str]) -> list[Path]:
    out: list[Path] = []
    for name in roots:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(_is_skipped_dir(p) for p in path.parts):
                continue
            if _should_skip_file(path):
                continue
            out.append(path)
    return sorted(out)


def _comment_kind(path: Path, stripped: str) -> bool:
    suf = path.suffix.lower()
    if not stripped:
        return False
    if suf == ".py":
        return stripped.startswith("#")
    if suf in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css"}:
        return (
            stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.endswith("*/")
        )
    if suf == ".sql":
        return stripped.startswith("--")
    if suf == ".sh":
        return stripped.startswith("#")
    return False


def _stat_file(path: Path) -> FileStat:
    text = path.read_text(encoding="utf-8", errors="ignore")
    physical = blank = comment = code = 0
    for line in text.splitlines():
        physical += 1
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif _comment_kind(path, stripped):
            comment += 1
        else:
            code += 1
    return FileStat(path=path, physical=physical, code=code, blank=blank, comment=comment)


def _area(path: Path) -> str:
    parts = path.relative_to(ROOT).parts
    if parts[0] == "services" and len(parts) > 1:
        return f"services/{parts[1]}"
    return parts[0]


def _lang(path: Path) -> str:
    suf = path.suffix.lower().lstrip(".")
    if suf in {"tsx", "ts"}:
        return suf
    if suf in {"js", "jsx", "mjs", "cjs"}:
        return "js"
    return suf or "other"


def _fmt_table(rows: list[tuple[str, int, int, int, int]], *, key: str) -> None:
    w = max(len(key), max((len(r[0]) for r in rows), default=0))
    print(f"{key:<{w}}  {'phys':>8}  {'code':>8}  {'blank':>7}  {'cmt':>7}")
    print(f"{'-' * w}  {'-' * 8}  {'-' * 8}  {'-' * 7}  {'-' * 7}")
    for name, phys, code, blank, cmt in rows:
        print(f"{name:<{w}}  {phys:8d}  {code:8d}  {blank:7d}  {cmt:7d}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Count under this top-level dir (repeatable). Default: services packages eval scripts",
    )
    parser.add_argument(
        "--by-file",
        action="store_true",
        help="List every counted file",
    )
    args = parser.parse_args()
    roots = args.roots or list(DEFAULT_ROOTS)

    files = _iter_code_files(roots)
    stats = [_stat_file(p) for p in files]

    by_area: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    totals = [0, 0, 0, 0]

    for s in stats:
        for bucket, key in ((by_area, _area(s.path)), (by_lang, _lang(s.path))):
            bucket[key][0] += s.physical
            bucket[key][1] += s.code
            bucket[key][2] += s.blank
            bucket[key][3] += s.comment
        totals[0] += s.physical
        totals[1] += s.code
        totals[2] += s.blank
        totals[3] += s.comment

    print("AgentPlatform LOC (source only)")
    print(f"roots: {', '.join(roots)}")
    print(
        "excludes: docs, workspace, seed, node_modules, dist, venv, "
        "lockfiles, md/json/yaml/toml, images"
    )
    print(f"files: {len(stats)}")
    print()
    print("By area")
    area_rows = [
        (k, *by_area[k])
        for k in sorted(by_area, key=lambda x: (-by_area[x][0], x))
    ]
    area_rows.append(("TOTAL", *totals))
    _fmt_table(area_rows, key="area")
    print()
    print("By language")
    lang_rows = [
        (k, *by_lang[k])
        for k in sorted(by_lang, key=lambda x: (-by_lang[x][0], x))
    ]
    lang_rows.append(("TOTAL", *totals))
    _fmt_table(lang_rows, key="lang")

    if args.by_file:
        print()
        print("By file")
        try:
            for s in sorted(stats, key=lambda x: (-x.physical, _rel(x.path))):
                print(f"{s.physical:6d}  {_rel(s.path)}")
        except BrokenPipeError:
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
