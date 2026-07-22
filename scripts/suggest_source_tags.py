#!/usr/bin/env python3
"""Offline sparse tag preview for sources (docs/15 §9 RQ1c).

Deterministic — path segments + header metadata only. No LLM.
Does not write files; print ``path\\ttags`` for review / CI sniff.

Usage:
  python scripts/suggest_source_tags.py seed/sources/writing
  python scripts/suggest_source_tags.py /workspace/sources
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installing the package.
_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME = _ROOT / "services" / "runtime"
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

from app.retrieval.chunking import extract_source_tags  # noqa: E402


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "seed/sources/writing").resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".markdown"}:
            continue
        if "cards" in {p.lower() for p in path.parts}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        tags = extract_source_tags(rel, text)
        print(f"{rel}\t{','.join(tags)}")
        count += 1
    print(f"# files={count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
