#!/usr/bin/env python3
"""Offline chunk quality audit (quality-uplift R §3.3).

Reports hard-cut rate, token-size histogram, share of chunks over 512 tokens,
and table-derived coverage. Index-path only — never call from StartTurn.

Usage:
  python scripts/retrieval/chunk_qa.py --root seed/sources/writing --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "services" / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "runtime"))


def _boundary_cut(part: str) -> bool:
    if not part:
        return True
    last = part[-1]
    return last in "\n \t。！？!?.;"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Corpus directory to walk")
    parser.add_argument("--limit", type=int, default=50, help="Max files to chunk")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from app.retrieval.chunking import chunk_source_text, should_index_source
    from app.retrieval.chunk_split import count_embed_tokens
    from app.retrieval.embedder import HashEmbedder

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    embedder = HashEmbedder(dimensions=64)
    n_chunks = 0
    n_hard = 0
    n_over_512 = 0
    n_table = 0
    tokens: list[int] = []
    files = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if files >= max(1, args.limit):
            break
        if not should_index_source(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        rel = str(path)
        chunks = chunk_source_text(path, rel, text, embedder=embedder, embed=False)
        files += 1
        for ch in chunks:
            body = str(ch.get("text") or "")
            n_chunks += 1
            if not _boundary_cut(body):
                n_hard += 1
            nt = count_embed_tokens(body)
            tokens.append(nt)
            if nt > 512:
                n_over_512 += 1
            cid = str(ch.get("chunk_id") or "")
            if "#table-" in cid or (body.startswith(str(ch.get("section_title") or "")) and " | " in body[:80]):
                n_table += 1

    report = {
        "files": files,
        "chunks": n_chunks,
        "hard_cut_rate": (n_hard / n_chunks) if n_chunks else 0.0,
        "over_512_token_rate": (n_over_512 / n_chunks) if n_chunks else 0.0,
        "table_like_chunks": n_table,
        "token_p50": sorted(tokens)[len(tokens) // 2] if tokens else 0,
        "token_max": max(tokens) if tokens else 0,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"files={report['files']} chunks={report['chunks']} "
            f"hard_cut_rate={report['hard_cut_rate']:.3f} "
            f"over_512={report['over_512_token_rate']:.3f} "
            f"table_like={report['table_like_chunks']} "
            f"token_p50={report['token_p50']} token_max={report['token_max']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
