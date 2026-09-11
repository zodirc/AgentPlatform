#!/usr/bin/env python3
"""档位基线评分（离线，不进产品 Turn）。

对当前 Work 手稿逐章跑表面层 + 平台原型对齐，写入
``eval/reports/writing/regime_baseline.json``，供 Ops 对照页读取。

真正的「2 本 × 10 章 strict 连写」需要在工作台用严格档写完后再对本脚本评分；
本脚本不编造章节、不下结论。
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
DEFAULT_OUT = ROOT / "eval" / "reports" / "writing" / "regime_baseline.json"

if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

    from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc  # noqa: E402
    from app.writing.ops_snapshot import collect_offline_metrics  # noqa: E402
    from app.writing.regime import resolve_regime  # noqa: E402
    from app.writing.signals.space import fit_signature, load_platform_space  # noqa: E402
    from app.writing.signals.surface import measure_surface  # noqa: E402


def _score_workspace(root: Path) -> dict[str, Any]:
    regime, source = resolve_regime(workspace_root=root)
    doc, rel = load_manuscript_doc(root)
    ids = list_section_ids(doc) if doc else []
    space = load_platform_space()
    chapters: list[dict[str, Any]] = []
    for sid in ids:
        body = extract_section(doc or "", sid) or ""
        if not body.strip():
            continue
        surface = measure_surface(body)
        fit = fit_signature(body, "mixed", space=space)
        chapters.append(
            {
                "section_id": sid,
                "visible_chars": int(surface.get("visible_chars") or 0),
                "surface": surface,
                "platform_alignment": round(float(fit.get("score") or 0.0), 4),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(root),
        "manuscript": rel,
        "regime": {"value": regime, "source": source},
        "chapter_count": len(chapters),
        "chapters": chapters,
        "metrics": collect_offline_metrics(workspace_root=root),
        "note": "本报告评现有手稿。2本×10章连写与20章对照需真人完成，脚本不下结论。",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--regime", choices=("author", "strict", "auto"), default="auto")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    from app.settings import settings

    root = (args.workspace or Path(settings.workspace_root)).resolve()
    payload = _score_workspace(root)
    if args.regime != "auto":
        payload["regime_filter"] = args.regime
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
