"""Process metrics for SWE-bench structural dual-track (CSI §8.3)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_DIFF_FILE_RE = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$", re.M)


def fingerprint_ids(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def load_instance_ids(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def files_from_patch(patch: str) -> set[str]:
    files: set[str] = set()
    for match in _DIFF_FILE_RE.finditer(patch or ""):
        name = match.group(1).strip()
        if name == "/dev/null":
            continue
        files.add(name.replace("\\", "/"))
    return files


def localization_hit_rate(
    *,
    model_patch: str,
    gold_patch: str,
) -> float | None:
    """|model_files ∩ gold_files| / |gold_files|. None if gold has no files."""
    gold = files_from_patch(gold_patch)
    if not gold:
        return None
    model = files_from_patch(model_patch)
    return len(model & gold) / len(gold)


def summarize_predictions(
    predictions: list[dict[str, Any]],
    gold_by_id: dict[str, str],
) -> dict[str, Any]:
    hits: list[float] = []
    empty_diff = 0
    missing_gold = 0
    for row in predictions:
        iid = str(row.get("instance_id") or row.get("id") or "")
        patch = str(row.get("model_patch") or row.get("patch") or "")
        if not patch.strip():
            empty_diff += 1
        gold = gold_by_id.get(iid, "")
        if not gold:
            missing_gold += 1
            continue
        rate = localization_hit_rate(model_patch=patch, gold_patch=gold)
        if rate is not None:
            hits.append(rate)
    return {
        "n_predictions": len(predictions),
        "empty_diff_count": empty_diff,
        "empty_diff_rate": (empty_diff / len(predictions)) if predictions else 0.0,
        "missing_gold_count": missing_gold,
        "file_localization_hit_rate_mean": (sum(hits) / len(hits)) if hits else None,
        "file_localization_n": len(hits),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pred", type=Path, required=True, help="Predictions JSONL")
    parser.add_argument(
        "--gold",
        type=Path,
        required=True,
        help="Gold JSONL with instance_id + patch|gold_patch",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--slice",
        type=Path,
        default=Path(__file__).with_name("lite50.txt"),
        help="Optional slice file to embed fingerprint",
    )
    args = parser.parse_args(argv)

    preds = _load_jsonl(args.pred)
    gold_rows = _load_jsonl(args.gold)
    gold_by_id: dict[str, str] = {}
    for row in gold_rows:
        iid = str(row.get("instance_id") or row.get("id") or "")
        patch = str(row.get("gold_patch") or row.get("patch") or row.get("model_patch") or "")
        if iid:
            gold_by_id[iid] = patch

    summary = summarize_predictions(preds, gold_by_id)
    if args.slice and args.slice.exists():
        ids = load_instance_ids(args.slice)
        summary["slice_path"] = str(args.slice)
        summary["slice_n"] = len(ids)
        summary["slice_fingerprint"] = fingerprint_ids(ids)

    text = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
