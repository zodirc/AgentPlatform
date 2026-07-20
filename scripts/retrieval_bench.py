#!/usr/bin/env python3
"""Offline retrieval A/B bench (docs/27 §8.1 layer 1 · docs/28 RE0/RE3)."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "services" / "runtime"
DEFAULT_QRELS = REPO_ROOT / "eval" / "retrieval" / "qrels.yaml"
DEFAULT_CORPUS = REPO_ROOT / "eval" / "retrieval" / "corpus"


def _ensure_runtime_path() -> None:
    sys.path.insert(0, str(RUNTIME_ROOT))


def _hit_paths(result: dict[str, Any]) -> list[str]:
    hits = result.get("hits") or []
    return [str(h.get("path", "")) for h in hits if isinstance(h, dict)]


def _recall_at_k(paths: list[str], expect: list[str], *, k: int) -> float:
    if not expect:
        return 1.0
    top = set(paths[:k])
    return 1.0 if any(p in top for p in expect) else 0.0


def _noise_count(paths: list[str], noise: list[str]) -> int:
    noise_set = set(noise)
    return sum(1 for p in paths if p in noise_set)


async def _run_case(
    case: dict[str, Any],
    *,
    k: int,
) -> dict[str, Any]:
    from app.tools.core import tools as core

    query = str(case["query"])
    expect_paths = list(case.get("expect_paths") or [])
    noise_paths = list(case.get("noise_paths") or [])
    path_prefix = case.get("path_prefix")
    expect_empty = bool(case.get("expect_empty"))

    a = await core.search_sources(query, limit=k)
    a_paths = _hit_paths(a)
    row: dict[str, Any] = {
        "id": case.get("id"),
        "query": query,
        "a_paths": a_paths,
        "a_recall": _recall_at_k(a_paths, expect_paths, k=k) if expect_paths else None,
        "a_noise": _noise_count(a_paths, noise_paths) if noise_paths else 0,
    }

    if path_prefix is not None:
        b = await core.search_sources(query, limit=k, path_prefix=str(path_prefix))
        b_paths = _hit_paths(b)
        row["path_prefix"] = path_prefix
        row["b_paths"] = b_paths
        row["b_filters"] = b.get("filters")
        row["b_hint"] = b.get("hint")
        if expect_empty:
            row["b_empty_ok"] = len(b_paths) == 0
            row["pass"] = bool(row["b_empty_ok"])
        else:
            row["b_recall"] = _recall_at_k(b_paths, expect_paths, k=k) if expect_paths else 1.0
            row["b_noise"] = _noise_count(b_paths, noise_paths) if noise_paths else 0
            if expect_paths:
                # Target must remain findable under the prefix (effect gate).
                recall_ok = row["b_recall"] >= 1.0
            else:
                recall_ok = True
            noise_ok = True
            if noise_paths and row["a_noise"] > 0:
                noise_ok = row["b_noise"] < row["a_noise"]
            elif noise_paths:
                noise_ok = row["b_noise"] == 0
            row["pass"] = bool(recall_ok and noise_ok)
    else:
        # Baseline-only case: A must hit expect_paths.
        row["pass"] = bool(
            _recall_at_k(a_paths, expect_paths, k=k) >= 1.0 if expect_paths else True
        )

    section = case.get("expect_section")
    if section and path_prefix is not None and not expect_empty:
        b = await core.search_sources(query, limit=k, path_prefix=str(path_prefix))
        titles = [
            str(h.get("section_title", ""))
            for h in (b.get("hits") or [])
            if isinstance(h, dict)
        ]
        row["b_section_hit"] = any(section in t for t in titles)
        # Section is soft for keyword mode; only fail hybrid if titles present and miss.
        if any(titles) and not row["b_section_hit"]:
            row["pass"] = False

    return row


async def main_async(*, qrels: Path, corpus: Path, k: int, mode: str) -> int:
    _ensure_runtime_path()

    from app.settings import settings
    from app.tools.core import tools as core

    data = yaml.safe_load(qrels.read_text(encoding="utf-8"))
    cases = list(data.get("cases") or [])
    if not cases:
        print("No cases in qrels", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="retrieval-bench-") as tmp:
        root = Path(tmp)
        sources = root / "sources"
        sources.mkdir(parents=True)
        shutil.copytree(corpus, sources, dirs_exist_ok=True)

        from app.retrieval.embedder import reset_embedder_cache

        reset_embedder_cache()
        settings.workspace_root = str(root)
        settings.data_dir = str(root / "data")
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        settings.retrieval_mode = mode
        settings.retrieval_backend = "json"
        settings.embedding_backend = "hash"
        settings.index_via_worker = False

        if mode != "keyword":
            await core.sync_sources_index()

        rows = []
        for case in cases:
            rows.append(await _run_case(case, k=k))

    passed = sum(1 for r in rows if r.get("pass"))
    failed = len(rows) - passed
    print(f"retrieval_bench mode={mode} k={k} pass={passed}/{len(rows)}")
    for row in rows:
        status = "PASS" if row.get("pass") else "FAIL"
        print(
            f"  [{status}] {row.get('id')}: "
            f"a_recall={row.get('a_recall')} b_recall={row.get('b_recall')} "
            f"a_noise={row.get('a_noise')} b_noise={row.get('b_noise')} "
            f"prefix={row.get('path_prefix')}"
        )
        if not row.get("pass"):
            print(f"         a_paths={row.get('a_paths')}")
            print(f"         b_paths={row.get('b_paths')}")
            if row.get("b_hint"):
                print(f"         hint={row.get('b_hint')}")

    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, default=DEFAULT_QRELS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=("keyword", "hybrid", "vector"),
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            main_async(qrels=args.qrels, corpus=args.corpus, k=args.k, mode=args.mode)
        )
    )


if __name__ == "__main__":
    main()
