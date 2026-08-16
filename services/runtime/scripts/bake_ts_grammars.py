#!/usr/bin/env python3
"""Prefetch tree-sitter grammars into the local pack cache (image bake / offline seed).

Languages match ``app.retrieval.chunking._EXT_TO_TS_LANG``. Runtime must not download
grammars on the hot path (see docs/plan/agent-workspace-ast-index.md).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Keep in sync with services/runtime/app/retrieval/chunking.py _EXT_TO_TS_LANG values.
BAKE_LANGUAGES = (
    "python",
    "javascript",
    "typescript",
    "tsx",
    "go",
    "rust",
    "java",
)


def _seed_from_dir(seed: Path, dest: Path) -> bool:
    """Copy a previously baked cache tree into dest if it looks populated."""
    if not seed.is_dir():
        return False
    files = [p for p in seed.rglob("*") if p.is_file() and p.name != "README.md"]
    if not files:
        return False
    dest.mkdir(parents=True, exist_ok=True)
    for src in files:
        rel = src.relative_to(seed)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    print(f"bake_ts_grammars: seeded {len(files)} files from {seed} → {dest}", flush=True)
    return True


def _required() -> bool:
    return os.environ.get("TS_GRAMMAR_BAKE_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_SEED_HINT = (
    "offline seed: populate deploy/ts-grammar-cache/ (compose build context "
    "ts_grammar_cache) from a networked host — see deploy/ts-grammar-cache/README.md: "
    "docker cp agent-runtime:/home/app/.cache/tree-sitter-language-pack/. "
    "deploy/ts-grammar-cache/ — then rebuild (make up-runtime / up-ast-indexer)"
)


def _fail_or_warn(msg: str) -> int:
    """Hard-fail when TS_GRAMMAR_BAKE_REQUIRED; else warn so China builds still ship."""
    if _required():
        print(f"bake_ts_grammars: ERROR {msg}\n  {_SEED_HINT}", file=sys.stderr)
        return 1
    print(
        f"bake_ts_grammars: WARN {msg} — image will use regex AST fallback "
        f"until rebuild with network/seed\n  {_SEED_HINT}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    seed = Path(os.environ.get("TS_GRAMMAR_SEED_DIR", "/tmp/ts-grammar-seed")).resolve()
    try:
        from tree_sitter_language_pack import (
            cache_dir,
            downloaded_languages,
            get_parser,
            prefetch,
        )
    except ImportError as exc:
        return _fail_or_warn(f"tree_sitter_language_pack missing: {exc}")

    dest = Path(cache_dir()).resolve()
    # cache_dir() is typically .../vX.Y.Z/libs — seed roots may be that libs dir,
    # the version dir, or the pack root. Prefer matching the parent chain.
    pack_root = dest.parent.parent if dest.name == "libs" else dest
    seeded = _seed_from_dir(seed, pack_root)
    if not seeded:
        # Also accept a seed that is already the libs directory layout.
        seeded = _seed_from_dir(seed, dest)

    have = {str(x) for x in (downloaded_languages() or [])}
    missing = [lang for lang in BAKE_LANGUAGES if lang not in have]
    if missing:
        print(f"bake_ts_grammars: prefetch missing {missing} (cache={dest})", flush=True)
        try:
            prefetch(list(BAKE_LANGUAGES))
        except Exception as exc:
            return _fail_or_warn(f"prefetch failed: {exc}")
        have = {str(x) for x in (downloaded_languages() or [])}
        missing = [lang for lang in BAKE_LANGUAGES if lang not in have]
        if missing:
            return _fail_or_warn(
                f"still missing after prefetch: {missing}; have={sorted(have)}"
            )
    else:
        print(f"bake_ts_grammars: cache already has required grammars ({dest})", flush=True)

    for lang in BAKE_LANGUAGES:
        try:
            get_parser(lang)
        except Exception as exc:
            return _fail_or_warn(f"get_parser({lang}) failed: {exc}")

    print(f"bake_ts_grammars: ok languages={list(BAKE_LANGUAGES)} cache={dest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
