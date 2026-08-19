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


_DIGITS = "零一二三四五六七八九"
_HTML_RE = re.compile(
    r"<!--\s*section:(?P<id>[^\s>]+)\s*-->\s*(?P<body>.*?)\s*<!--\s*/section:(?P=id)\s*-->",
    re.DOTALL,
)
_HTML_MARK = re.compile(r"<!--\s*/?section:[^>]+-->[ \t]*\n?")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_CH_ID = re.compile(r"^(?:ch|chapter|section)[_-]?0*(\d+)$", re.I)


def _title(sid: str) -> str:
    match = _CH_ID.fullmatch(sid.strip())
    if not match:
        return sid.strip()
    n = int(match.group(1))
    if 1 <= n <= 9:
        return f"第{_DIGITS[n]}章"
    if n == 10:
        return "第十章"
    if n < 20:
        return f"第十{_DIGITS[n - 10]}章"
    if n < 100:
        ten, one = divmod(n, 10)
        return f"第{_DIGITS[ten]}十{(_DIGITS[one] if one else '')}章"
    return f"第{n}章"


def _id_from_heading(title: str) -> str:
    heading = title.strip()
    match = re.match(r"^第\s*([0-9]+|[一二三四五六七八九十]+)\s*章", heading)
    if match:
        token = match.group(1)
        if token.isdigit():
            return f"ch{int(token)}"
        # 一…十 only; migrate is best-effort for Chinese numerals.
        if token in _DIGITS:
            return f"ch{_DIGITS.index(token)}"
        if token == "十":
            return "ch10"
    match = _CH_ID.fullmatch(heading)
    if match:
        return f"ch{int(match.group(1))}"
    return heading


def _format(sid: str, content: str) -> str:
    body = _HTML_MARK.sub("", content).strip("\n")
    title = _title(sid)
    if body:
        return f"# {title}\n\n{body}"
    return f"# {title}"


def _list_ids(doc: str) -> list[str]:
    html = [m.group("id") for m in _HTML_RE.finditer(doc or "")]
    if html:
        return html
    return [_id_from_heading(m.group(1)) for m in _H1_RE.finditer(doc or "")]


def _upsert(doc: str, sid: str, content: str) -> str:
    block = _format(sid, content)
    title = _title(sid)
    heading = f"# {title}"
    if heading in (doc or ""):
        pattern = re.compile(re.escape(heading) + r"(?:\n.*?)(?=\n# |\Z)", re.DOTALL)
        updated, n = pattern.subn(block, doc, count=1)
        if n:
            return updated if updated.endswith("\n") else updated + "\n"
    start, end = f"<!-- section:{sid} -->", f"<!-- /section:{sid} -->"
    if start in (doc or "") and end in (doc or ""):
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        updated, n = pattern.subn(block, doc, count=1)
        if n:
            return updated if updated.endswith("\n") else updated + "\n"
    base = (doc or "").rstrip()
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
