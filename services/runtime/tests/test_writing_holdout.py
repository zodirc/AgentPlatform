from __future__ import annotations

from app.writing.signals.bank import load_platform_exemplars
from app.writing.signals.holdout import (
    HOLDOUT_N_MIN,
    HOLDOUT_WORKS,
    JINJIUYE_PROBE,
    SPLIT_VERSION,
    THIN_OK_FRAGMENTS,
    TRAIN_WORKS,
    filter_exemplars,
    load_eval_holdout_exemplars,
    split_of_work,
    summarize_holdout,
    unlabeled_works,
)
from app.writing.signals.prefs_loader import _module as _writing_prefs

_wp = _writing_prefs()


def test_holdout_works_are_not_train() -> None:
    assert "祝福" not in TRAIN_WORKS
    assert "春风沉醉的晚上" not in TRAIN_WORKS
    assert "伤逝" not in TRAIN_WORKS
    assert TRAIN_WORKS.isdisjoint(HOLDOUT_WORKS)


def test_catalog_works_are_partitioned() -> None:
    works = {entry["work"] for rows in _wp.EXEMPLAR_CATALOG.values() for entry in rows}
    assert works <= (TRAIN_WORKS | HOLDOUT_WORKS)
    bank = load_platform_exemplars()
    assert unlabeled_works(bank) == []
    assert split_of_work("祝福") == "holdout"
    assert split_of_work("孔乙己") == "train"
    assert split_of_work("伤逝") == "holdout"


def test_production_bank_excludes_eval_holdout() -> None:
    bank = load_platform_exemplars()
    live_works = {s.work for samples in bank.values() for s in samples}
    assert "伤逝" not in live_works
    assert "在酒楼上" not in live_works
    assert "肥皂" not in live_works
    assert "明天" not in live_works
    for frag in _wp.FRAGMENT_TYPES:
        assert len(bank[frag]) == 4, frag
    eval_bank = load_eval_holdout_exemplars()
    eval_works = {s.work for samples in eval_bank.values() for s in samples}
    assert "伤逝" in eval_works
    assert eval_works <= HOLDOUT_WORKS
    assert eval_works.isdisjoint(TRAIN_WORKS)
    assert all(s.scope == "holdout_eval" for samples in eval_bank.values() for s in samples)


def test_filter_exemplars_no_work_leak() -> None:
    bank = load_platform_exemplars()
    train = filter_exemplars(bank, split="train")
    hold = filter_exemplars(bank, split="holdout")
    train_works = {s.work for samples in train.values() for s in samples}
    hold_works = {s.work for samples in hold.values() for s in samples}
    assert train_works <= TRAIN_WORKS
    assert hold_works <= HOLDOUT_WORKS
    assert "祝福" not in train_works
    assert "春风沉醉的晚上" not in train_works
    assert "祝福" in hold_works
    assert "春风沉醉的晚上" in hold_works
    assert "伤逝" not in hold_works


def test_summarize_holdout_report_shape() -> None:
    report = summarize_holdout()
    assert report["split_version"] == SPLIT_VERSION
    assert SPLIT_VERSION == "work-v2"
    assert report["schema_id"] == _wp.FEATURE_SCHEMA_ID
    assert set(report["fragments"]) == set(_wp.FRAGMENT_TYPES)
    assert report["holdout_gate"]["passed"] is True
    assert report["holdout_gate"]["min_n"] == HOLDOUT_N_MIN
    dialogue = report["fragments"]["dialogue_dyad"]
    assert dialogue["n_train"] >= 1
    assert dialogue["n_holdout"] >= HOLDOUT_N_MIN
    assert dialogue["mean_abs_delta"] is not None
    assert "short_quote_run" in dialogue["train_mean"]
    assert "exemplar_alignment" not in dialogue["train_mean"]
    for frag, row in report["fragments"].items():
        if frag in THIN_OK_FRAGMENTS:
            assert row["n_holdout"] >= 1
            continue
        assert row["n_holdout"] >= HOLDOUT_N_MIN, frag
        assert row["thin"] is False
    battle = report["fragments"]["battle_action"]
    assert battle["n_holdout"] >= 1
    probe = report["probe"]
    assert probe["id"] == "jinjiuye_dyad"
    assert probe["gold"] is False
    assert JINJIUYE_PROBE.startswith("「金九爷")
    assert probe["l1_alignment_to_train"] is not None
    assert 0.0 <= float(probe["l1_alignment_to_train"]) <= 1.0
