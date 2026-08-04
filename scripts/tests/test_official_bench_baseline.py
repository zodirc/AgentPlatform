from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.baseline import (  # noqa: E402
    compare_latest_to_baseline,
    extract_suite_snapshot,
    infer_sample_tier,
    render_scorecard,
    suite_metrics,
)


def test_extract_retrieval_snapshot_prefers_hybrid() -> None:
    manifest = {
        "id": "r1",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-02T00:00:00+00:00",
        "metrics": {
            "ndcg_at_10": 0.4,
            "hybrid.ndcg_at_10": 0.41,
            "bm25.ndcg_at_10": 0.39,
            "delta_vs_bm25.ndcg_at_10": 0.02,
            "recall_at_100": 0.5,
            "hybrid.recall_at_100": 0.55,
        },
        "cases": [
            {
                "case_id": "beir.fiqa.hybrid",
                "status": "pass",
                "metrics": {"ndcg_at_10": 0.27, "recall_at_100": 0.58},
            }
        ],
    }
    snap = extract_suite_snapshot(manifest)
    assert snap is not None
    assert snap["metrics"]["ndcg_at_10"] == 0.41
    assert snap["bm25_metrics"]["ndcg_at_10"] == 0.39
    assert snap["cases"]["beir.fiqa.hybrid"]["ndcg_at_10"] == 0.27


def test_skip_dry_context() -> None:
    manifest = {
        "id": "c1",
        "official_suite": "context",
        "status": "completed",
        "dry_metrics": True,
        "metrics": {"full_f1": 0.1},
    }
    assert extract_suite_snapshot(manifest) is None


def test_suite_metrics_reads_block() -> None:
    doc = {"suites": {"retrieval": {"metrics": {"ndcg_at_10": 0.42}}}}
    m = suite_metrics(doc, "retrieval")
    assert m == {"ndcg_at_10": 0.42}


def test_extract_agent_retrieval_prefers_agent_prefix() -> None:
    manifest = {
        "id": "r-l1",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-02T00:00:00+00:00",
        "model_meta": {
            "protocol_version": "official-small-2026-08-m3",
            "eval_path": "agent",
            "arm": "free",
            "sample_tier": "smoke",
        },
        "metrics": {
            "ndcg_at_10": 0.40,
            "agent.ndcg_at_10": 0.403,
            "hybrid.ndcg_at_10": 0.41,
            "recall_at_100": 0.60,
            "agent.recall_at_100": 0.6019,
            "agent.n_queries": 20.0,
        },
    }
    snap = extract_suite_snapshot(manifest)
    assert snap is not None
    assert snap["eval_path"] == "agent"
    assert snap["primary_arm"] == "free"
    assert snap["sample_tier"] == "smoke"
    assert snap["metrics"]["ndcg_at_10"] == 0.403
    assert snap["protocol_version"] == "official-small-2026-08-m3"


def test_infer_sample_tier() -> None:
    assert infer_sample_tier(suite="retrieval", limit_queries=20) == "smoke"
    assert infer_sample_tier(suite="retrieval", limit_queries=0) == "anchor"
    assert infer_sample_tier(suite="context", context_limit=10) == "smoke"
    assert infer_sample_tier(suite="context", context_limit=0) == "anchor"
    assert (
        infer_sample_tier(suite="coding", coding_tier="n25", harness=True) == "anchor"
    )
    assert (
        infer_sample_tier(suite="coding", coding_tier="n5", harness=False) == "smoke"
    )


def test_scorecard_dual_sections() -> None:
    md = render_scorecard(
        {
            "protocol_version": "official-small-2026-08-m3",
            "eval_path": "agent",
            "updated_at": "2026-08-03T00:00:00+00:00",
            "suites": {
                "retrieval": {
                    "run_id": "a1",
                    "sample_tier": "anchor",
                    "primary_arm": "free",
                    "metrics": {"ndcg_at_10": 0.4, "recall_at_100": 0.5, "n_queries": 400},
                }
            },
            "smoke_suites": {
                "retrieval": {
                    "run_id": "s1",
                    "sample_tier": "smoke",
                    "primary_arm": "free",
                    "metrics": {"ndcg_at_10": 0.35, "recall_at_100": 0.4, "n_queries": 20},
                }
            },
        }
    )
    assert "主栏 · 锚点档" in md
    assert "冒烟趋势" in md
    assert "不作效果结论" in md


def test_compare_refuses_tier_mismatch(tmp_path: Path, monkeypatch) -> None:
    import official_bench.baseline as bl

    monkeypatch.setattr(bl, "BASELINE_DIR", tmp_path)
    monkeypatch.setattr(bl, "reports_dir", lambda: tmp_path)
    (tmp_path / "official-small-2026-08-m3.json").write_text(
        json.dumps(
            {
                "protocol_version": "official-small-2026-08-m3",
                "suites": {
                    "retrieval": {
                        "sample_tier": "anchor",
                        "metrics": {
                            "ndcg_at_10": 0.5,
                            "recall_at_100": 0.6,
                            "map_at_100": 0.4,
                        },
                    }
                },
                "smoke_suites": {},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "latest_retrieval.json").write_text(
        json.dumps(
            {
                "id": "smoke1",
                "official_suite": "retrieval",
                "status": "completed",
                "finished_at": "2026-08-03T00:00:00+00:00",
                "model_meta": {
                    "protocol_version": "official-small-2026-08-m3",
                    "eval_path": "agent",
                    "sample_tier": "smoke",
                    "arm": "free",
                },
                "metrics": {
                    "agent.ndcg_at_10": 0.3,
                    "agent.recall_at_100": 0.4,
                    "agent.map_at_100": 0.2,
                    "agent.n_queries": 20.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bl, "protocol_from_latest", lambda: "official-small-2026-08-m3")
    report = compare_latest_to_baseline(suites=("retrieval",))
    statuses = {r.get("status") for r in report["rows"] if r.get("status")}
    assert "tier_mismatch" in statuses


def test_paired_case_delta_report_bootstrap() -> None:
    from official_bench.baseline import paired_case_delta_report

    base = {f"beir.fiqa.q-{i}": {"ndcg_at_10": 0.2} for i in range(20)}
    latest = {
        f"beir.fiqa.q-{i}": {"ndcg_at_10": 0.2 + (0.1 if i < 15 else -0.05)}
        for i in range(20)
    }
    report = paired_case_delta_report(base, latest, metric="ndcg_at_10")
    assert report["n_paired"] == 20
    assert report["wins"] == 15
    assert report["losses"] == 5
    assert report["ties"] == 0
    assert report["mean_delta"] is not None and report["mean_delta"] > 0
    assert report["bootstrap_ci95"] is not None
    assert report["ci_includes_zero"] is False
    assert report["verdict"] == "positive"


def test_paired_case_delta_ci_includes_zero() -> None:
    from official_bench.baseline import paired_case_delta_report

    base = {f"c{i}": {"ndcg_at_10": 0.5} for i in range(20)}
    latest = {
        f"c{i}": {"ndcg_at_10": 0.5 + (0.01 if i % 2 == 0 else -0.01)} for i in range(20)
    }
    report = paired_case_delta_report(base, latest, metric="ndcg_at_10")
    assert report["ci_includes_zero"] is True
    assert report["verdict"] == "no_stable_delta"