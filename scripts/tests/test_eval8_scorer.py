"""EVAL-8 · Official LongBench / SQuAD scorer parity tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.context_run import (  # noqa: E402
    SCORER_VERSION,
    extract_pred_answer,
    normalize_answer,
    score_prediction,
)


def test_scorer_version_is_v2() -> None:
    assert SCORER_VERSION == "v2"


def test_normalize_answer_matches_official_longbench() -> None:
    assert normalize_answer("Flexibility.") == "flexibility"
    assert normalize_answer("Watt, one joule per second.") == "watt one joule per second"
    assert normalize_answer("She is an American.") == "she is american"
    assert normalize_answer("Pierre Grassou.") == "pierre grassou"
    assert normalize_answer("  The Answer. ") == "answer"


def test_eval8_section79_near_miss_pairs() -> None:
    """Pairs documented in brief §7.9 — v1 zeros, v2 recovers."""
    pairs = [
        ("watt", "Watt, one joule per second.", 0.0, 1 / 3),
        ("flexibility", "Flexibility.", 0.0, 1.0),
        ("Pierre Grassou.", "Grassou", 0.0, 2 / 3),
        ("American", "She is an American.", 0.0, 0.5),
    ]
    for pred, gold, _v1_expect, v2_expect in pairs:
        v1 = score_prediction(pred, [gold], scorer="v1")
        v2 = score_prediction(pred, [gold], scorer="v2")
        assert v1["f1"] == 0.0, (pred, gold, v1)
        assert abs(v2["f1"] - v2_expect) < 1e-9, (pred, gold, v2, v2_expect)


def test_em_v2_no_substring_clause() -> None:
    # v1 granted EM via gold ⊆ pred; v2 requires normalized equality.
    pred = "She is an American."
    gold = "American"
    assert score_prediction(pred, [gold], scorer="v1")["em"] == 1.0
    assert score_prediction(pred, [gold], scorer="v2")["em"] == 0.0
    assert score_prediction("American", [gold], scorer="v2")["em"] == 1.0


def test_default_score_prediction_is_v2() -> None:
    s = score_prediction("flexibility", ["Flexibility."])
    assert s["f1"] == 1.0
    assert s["em"] == 1.0


def test_extract_pred_answer_last_labeled_line() -> None:
    assert extract_pred_answer("**Answer:** Berlin") == "Berlin"
    assert extract_pred_answer("Answer: <phrase>\nAnswer: Berlin") == "Berlin"
    assert extract_pred_answer("The capital is X.\nAnswer: Berlin") == "Berlin"
    # No labeled line → leave prose (v2 EM still exact-equality).
    assert extract_pred_answer("the needle is here") == "the needle is here"
    # Gold-shaped text without the label is not extracted.
    assert extract_pred_answer("  The Answer. ") == "  The Answer. "


def test_score_prediction_strips_answer_prefix() -> None:
    """X-3 agent format vs completion LongBench: label must not zero EM."""
    labeled = score_prediction("Answer: Berlin", ["berlin"])
    assert labeled["em"] == 1.0
    assert labeled["f1"] == 1.0
    mixed = score_prediction("I read the file.\nAnswer: Flexibility.", ["Flexibility."])
    assert mixed["em"] == 1.0
    assert mixed["f1"] == 1.0
    # Prefix path is pred-only; golds are unchanged.
    assert score_prediction("Berlin", ["Answer: Berlin"])["em"] == 0.0
