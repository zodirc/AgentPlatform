#!/usr/bin/env python3
"""L2 叙事体检。默认不调 LLM：发表基线 + L1 诚实化 + C 条准入。

有 WRITING_L2_JUDGE_CMD 时才跑评委。不阻塞合入，不进产品 Turn。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
DEFAULT_MD = ROOT / "reports" / "writing-narrative-baseline.md"
DEFAULT_JSON = ROOT / "eval" / "reports" / "writing" / "latest_l2.json"

if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.writing.narrative.corpus import iter_sample_texts, literary_human_samples  # noqa: E402
from app.writing.narrative.honesty import (  # noqa: E402
    summarize_exemplar_alignment,
    summarize_staccato_dialogue,
)
from app.writing.narrative.report import render_baseline_markdown  # noqa: E402
from app.writing.narrative.vector import encode_feature_map, mean_rarity_percentile  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_MD)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args(argv)

    honesty = {
        "exemplar_alignment": summarize_exemplar_alignment(),
        "staccato_dialogue": summarize_staccato_dialogue(),
    }
    samples = literary_human_samples()
    md = render_baseline_markdown(
        honesty=honesty,
        product_n=0,
        literary_n=len(samples),
        rarity=None,
        agreement=None,
        judge_mode="baseline-no-llm",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "honesty": honesty,
        "literary_n": len(samples),
        "product_n": 0,
        "sample_slugs": [row["path"] for row in iter_sample_texts(samples)[:40]],
    }
    # Touch encode path so rarity math stays imported in the periodic job.
    payload["vector_dim"] = len(encode_feature_map({}))
    payload["rarity_smoke"] = mean_rarity_percentile(
        encode_feature_map({}),
        [encode_feature_map({}), encode_feature_map({"affect_embodied": 0.3})],
        k=2,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(args.out))
    print(str(args.json_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
