from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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


def test_eval4_paired_highlights() -> None:
    from official_bench.baseline import paired_case_delta_report

    base = {f"beir.fiqa.q-{i}": {"ndcg_at_10": 0.2} for i in range(10)}
    latest = {
        f"beir.fiqa.q-{i}": {"ndcg_at_10": 0.5 if i < 3 else (0.05 if i >= 8 else 0.2)}
        for i in range(10)
    }
    report = paired_case_delta_report(
        base, latest, metric="ndcg_at_10", top_k_highlights=3
    )
    assert len(report["improvements"]) == 3
    assert len(report["regressions"]) == 2
    assert report["improvements"][0]["delta"] > 0
    assert report["regressions"][0]["delta"] < 0


def test_eval4_trajectory_enrichment_and_eval5_noise(tmp_path, monkeypatch) -> None:
    from official_bench import baseline as bl

    monkeypatch.setattr(bl, "reports_dir", lambda: tmp_path)
    man_a = {
        "id": "run-a",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-04T00:00:00+00:00",
        "model_meta": {
            "protocol_version": "official-small-2026-08-m3",
            "eval_path": "agent",
            "arm": "free",
            "sample_tier": "smoke",
        },
        "metrics": {"agent.ndcg_at_10": 0.4, "agent.n_queries": 5.0},
        "cases": [
            {
                "case_id": f"beir.fiqa.q-{i}",
                "status": "pass",
                "metrics": {"ndcg_at_10": 0.2},
                "bucket": "ok",
                "tools": ["search_sources"],
                "queries": [f"q{i}"],
                "top_hits": [{"doc_id": f"d{i}", "score": 1.0}],
            }
            for i in range(8)
        ],
    }
    man_b = {
        "id": "run-b",
        "official_suite": "retrieval",
        "status": "completed",
        "finished_at": "2026-08-04T01:00:00+00:00",
        "model_meta": {
            "protocol_version": "official-small-2026-08-m3",
            "eval_path": "agent",
            "arm": "free",
            "sample_tier": "smoke",
        },
        "metrics": {"agent.ndcg_at_10": 0.5, "agent.n_queries": 8.0},
        "cases": [
            {
                "case_id": f"beir.fiqa.q-{i}",
                "status": "pass",
                "metrics": {"ndcg_at_10": 0.4 if i < 6 else 0.1},
                "bucket": "weak_hits" if i >= 6 else "ok",
                "tools": ["search_sources", "read_file"],
                "queries": [f"q{i}"],
                "top_hits": [{"doc_id": f"d{i}", "score": 1.2}],
            }
            for i in range(8)
        ],
    }
    report = bl.compare_two_manifests(man_a, man_b)
    assert report["n_paired"] == 8
    assert report["verdict"] in {"positive", "no_stable_delta"}
    assert "trajectory_highlights" in report
    assert report["improvements"]
    assert report["improvements"][0]["a"]["tools"] == ["search_sources"]
    assert "noise_band" in report
    assert (tmp_path / "noise_band" / "archive.json").is_file()
    # Second compare should dedup same a/b pair
    report2 = bl.compare_two_manifests(man_a, man_b)
    archive = json.loads((tmp_path / "noise_band" / "archive.json").read_text())
    assert len(archive["pairs"]) == 1
    assert report2["noise_band"]["n_archive_pairs"] == 1


def test_gold_read_case_stats_and_aggregate() -> None:
    from official_bench.agent_path_extract import (
        gold_read_case_stats,
        read_doc_ids_from_events,
        read_targets_from_events,
    )
    from official_bench.l2_probes import gold_read_aggregate

    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "sources/beir/fiqa/111.txt"},
            },
        },
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "sources/beir/fiqa/222.txt"},
            },
        },
    ]
    targets = read_targets_from_events(events)
    assert [t["doc_id"] for t in targets] == ["111", "222"]
    assert read_doc_ids_from_events(events) == ["111", "222"]

    unread = gold_read_case_stats(
        ranked_doc_ids=["111", "999", "222"],
        read_doc_ids=["999"],
        gold_doc_ids={"111", "222"},
    )
    assert unread["failure_slice"] == "gold_on_ranked_but_unread"
    assert unread["gold_on_ranked_but_unread_n"] == 2
    assert unread["read_any_gold"] is False

    read_ok = gold_read_case_stats(
        ranked_doc_ids=["111", "222"],
        read_doc_ids=["111"],
        gold_doc_ids={"111"},
    )
    assert read_ok["failure_slice"] == "gold_read"
    assert read_ok["read_target_ranks"] == [1]

    absent = gold_read_case_stats(
        ranked_doc_ids=["aaa"],
        read_doc_ids=["aaa"],
        gold_doc_ids={"gold"},
    )
    assert absent["failure_slice"] == "gold_absent_from_ranked"

    cases = [
        {
            "case_id": "beir.fiqa.q-1",
            "read_any_gold": False,
            "gold_read_failure_slice": "gold_on_ranked_but_unread",
            "gold_on_ranked_n": 1,
            "gold_on_ranked_but_unread_n": 1,
            "read_target_ranks": [3],
        },
        {
            "case_id": "beir.fiqa.q-2",
            "read_any_gold": True,
            "gold_read_failure_slice": "gold_read",
            "gold_on_ranked_n": 1,
            "gold_on_ranked_but_unread_n": 0,
            "read_target_ranks": [1],
        },
    ]
    agg = gold_read_aggregate(cases)
    assert agg["n_scored"] == 2
    assert agg["gold_read_rate"] == 0.5
    assert agg["n_gold_on_ranked_but_unread"] == 1
    assert agg["by_dataset"]["fiqa"]["n"] == 2


def test_ret15_score_audit_never_triggers() -> None:
    from official_bench.batch6_offline_analysis import ret15_score_audit

    man = {
        "cases": [
            {
                "case_id": f"beir.fiqa.q-{i}",
                "top_hits": [{"doc_id": "d", "score": 1.2}],
            }
            for i in range(8)
        ]
    }
    rep = ret15_score_audit(man, threshold=0.15)
    assert rep["adjudication"] == "never_triggers"
    assert rep["open_ret15_stage2_normalize"] is True
    assert rep["top1_trigger_rate"] == 0.0


def test_ctx10_classifies_scorer_alias() -> None:
    from official_bench.batch6_offline_analysis import ctx10_wrong_answer

    man = {
        "cases": [
            {
                "case_id": "longbench.hotpotqa.1",
                "bucket": "wrong_answer_after_read",
                "pred": "Paris",
                "metrics": {"em": 1.0, "f1": 0.0},
                "read_coverage": 0.5,
                "n_reads": 2,
                "used_next_offset": True,
                "turn_id": None,
            },
            {
                "case_id": "longbench.narrativeqa.2",
                "bucket": "wrong_answer_after_read",
                "pred": "wrong",
                "metrics": {"em": 0.0, "f1": 0.0},
                "read_coverage": 0.02,
                "n_reads": 1,
                "used_next_offset": False,
                "turn_id": None,
            },
        ]
    }
    rep = ctx10_wrong_answer(man)
    assert rep["n_wrong_answer"] == 2
    assert rep["class_counts"].get("iii_scorer_alias") == 1
    assert rep["class_counts"].get("ii_localization_miss") == 1


def test_scorecard_appends_notes(tmp_path: Path, monkeypatch) -> None:
    import official_bench.baseline as bl

    monkeypatch.setattr(bl, "BASELINE_DIR", tmp_path)
    (tmp_path / "SCORECARD.notes.md").write_text(
        "# notes\n\nHAND_NOTE_MARKER\n", encoding="utf-8"
    )
    md = render_scorecard(
        {
            "protocol_version": "official-small-2026-08-m3",
            "eval_path": "agent",
            "updated_at": "2026-08-14T00:00:00+00:00",
            "suites": {},
            "smoke_suites": {},
        }
    )
    assert "HAND_NOTE_MARKER" in md
    assert "SCORECARD.notes.md" in md
    # Idempotent: notes appear once under the appendix heading.
    assert md.count("HAND_NOTE_MARKER") == 1


def test_promote_run_refuses_smoke(tmp_path: Path, monkeypatch) -> None:
    import official_bench.baseline as bl

    monkeypatch.setattr(bl, "BASELINE_DIR", tmp_path)
    runs = tmp_path / "runs" / "smoke-run"
    runs.mkdir(parents=True)
    (tmp_path / "official-small-2026-08-m3.json").write_text(
        json.dumps(
            {
                "protocol_version": "official-small-2026-08-m3",
                "eval_path": "agent",
                "suites": {},
                "smoke_suites": {},
            }
        ),
        encoding="utf-8",
    )
    (runs / "manifest.json").write_text(
        json.dumps(
            {
                "id": "smoke-run",
                "official_suite": "coding",
                "status": "completed",
                "finished_at": "2026-08-13T00:00:00+00:00",
                "model_meta": {
                    "protocol_version": "official-small-2026-08-m3",
                    "eval_path": "agent",
                    "sample_tier": "smoke",
                    "coding_tier": "n5",
                    "harness": True,
                    "config_fingerprint": "fp-test",
                    "model_snapshot": {"model": "x"},
                },
                "metrics": {
                    "resolve_rate": 0.6,
                    "patch_rate": 1.0,
                    "n_instances": 5,
                    "coding_tier": "n5",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sample_tier='smoke'"):
        bl.promote_run_to_baseline("smoke-run", reports=tmp_path)


def test_promote_run_accepts_anchor(tmp_path: Path, monkeypatch) -> None:
    import official_bench.baseline as bl

    monkeypatch.setattr(bl, "BASELINE_DIR", tmp_path)
    runs = tmp_path / "runs" / "anchor-run"
    runs.mkdir(parents=True)
    (tmp_path / "official-small-2026-08-m3.json").write_text(
        json.dumps(
            {
                "protocol_version": "official-small-2026-08-m3",
                "eval_path": "agent",
                "suites": {},
                "smoke_suites": {"retrieval": {"run_id": "old-smoke"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "SCORECARD.notes.md").write_text("NOTE_KEEP\n", encoding="utf-8")
    (runs / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor-run",
                "official_suite": "context",
                "status": "completed",
                "finished_at": "2026-08-14T00:00:00+00:00",
                "model_meta": {
                    "protocol_version": "official-small-2026-08-m3",
                    "eval_path": "agent",
                    "sample_tier": "anchor",
                    "arm": "free",
                    "context_limit": 0,
                    "config_fingerprint": "fp-anchor",
                    "settings_snapshot": {"x": 1},
                    "model": "test-model",
                },
                "metrics": {"agent_f1": 0.5, "agent_em": 0.25},
            }
        ),
        encoding="utf-8",
    )
    path, doc = bl.promote_run_to_baseline("anchor-run", reports=tmp_path)
    assert path.is_file()
    assert "context" in doc["suites"]
    assert doc["suites"]["context"]["run_id"] == "anchor-run"
    assert doc["smoke_suites"]["retrieval"]["run_id"] == "old-smoke"
    scorecard = (tmp_path / "SCORECARD.md").read_text(encoding="utf-8")
    assert "NOTE_KEEP" in scorecard
    assert "anchor-run" in scorecard


def test_promote_b3357dd6_smoke_negative() -> None:
    """A0 exit criterion: real n5+harness run must be refused."""
    import official_bench.baseline as bl

    rid = "b3357dd6-19d5-4669-ae06-ec3bc1a50d27"
    man = bl.reports_dir() / "runs" / rid / "manifest.json"
    if not man.is_file():
        pytest.skip("b3357dd6 artifacts not present on this machine")
    with pytest.raises(ValueError, match="sample_tier="):
        bl.promote_run_to_baseline(rid)
