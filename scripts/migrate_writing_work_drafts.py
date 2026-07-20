"""Migrate split chapter drafts into a monofile manuscript draft (docs/23).

Dry-run by default. Does not require runtime deps.

Usage:
  python3 scripts/migrate_writing_work_drafts.py --workspace ./workspace
  python3 scripts/migrate_writing_work_drafts.py --workspace ./workspace --apply
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _start(sid: str) -> str:
    return f"<!-- section:{sid} -->"


def _end(sid: str) -> str:
    return f"<!-- /section:{sid} -->"


def _format(sid: str, content: str) -> str:
    return f"{_start(sid)}\n{content.strip(chr(10))}\n{_end(sid)}"


def _list_ids(doc: str) -> list[str]:
    return re.findall(r"<!--\s*section:([^\s>]+)\s*-->", doc)


def _upsert(doc: str, sid: str, content: str) -> str:
    block = _format(sid, content)
    start, end = _start(sid), _end(sid)
    if start in doc and end in doc:
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        updated, n = pattern.subn(block, doc, count=1)
        if n:
            return updated if updated.endswith("\n") else updated + "\n"
    base = doc.rstrip()
    return f"{base}\n\n{block}\n" if base else f"{block}\n"


def _collect_split(root: Path) -> dict[str, Path]:
    found: dict[str, tuple[float, Path]] = {}

    def consider(path: Path) -> None:
        if not path.is_file() or path.suffix != ".md" or path.name == "manuscript.md":
            return
        sid = path.stem
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        prev = found.get(sid)
        if prev is None or mtime >= prev[0]:
            found[sid] = (mtime, path)

    for base in (
        root / ".agent" / "work" / "drafts",
        root / ".agent" / "revisions",
    ):
        if base.is_dir():
            for p in base.rglob("*.md"):
                consider(p)
    sessions = root / ".agent" / "sessions"
    if sessions.is_dir():
        for p in sessions.glob("*/revisions/*/*.md"):
            consider(p)
    return {sid: path for sid, (_, path) in found.items()}


def migrate(workspace: Path, *, apply: bool) -> list[str]:
    root = workspace.resolve()
    messages: list[str] = []
    dest = root / ".agent" / "work" / "drafts" / "manuscript.md"
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    present = set(_list_ids(existing))
    split = _collect_split(root)
    if not split and not existing:
        messages.append("no drafts found")
        return messages

    doc = existing
    for sid, src in sorted(split.items()):
        if sid in present:
            messages.append(f"skip {sid}: already in draft manuscript")
            continue
        body = src.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"<!--\s*/?section:[^>]+-->", "", body).strip()
        doc = _upsert(doc, sid, body)
        messages.append(
            f"{'would merge' if not apply else 'merged'} {src.relative_to(root)} → drafts/manuscript.md#{sid}"
        )

    if apply and doc != existing:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(doc if doc.endswith("\n") else doc + "\n", encoding="utf-8")
        confirmed = root / "manuscript.md"
        if not confirmed.exists():
            confirmed.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")
            messages.append("created manuscript.md from draft")
    elif not apply and doc != existing:
        messages.append(
            f"(dry-run) manuscript draft would have {len(_list_ids(doc))} section(s)"
        )
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.workspace.is_dir():
        raise SystemExit(f"workspace not found: {args.workspace}")
    for line in migrate(args.workspace, apply=args.apply):
        print(line)


if __name__ == "__main__":
    main()
