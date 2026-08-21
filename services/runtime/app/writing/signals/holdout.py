"""Train/holdout split of the platform exemplar bank (report only).

Does not change production prefs, net, or the live prototype space.
Eval-only passages live in ``exemplars_holdout/`` and are never loaded by
``load_platform_exemplars``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.writing.signals.bank import (
    Exemplar,
    load_exemplars_dir,
    load_platform_exemplars,
)
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.scorer import score_writing_fragment
from app.writing.signals.signature import (
    SIGNATURE_KEYS,
    extract_signature,
    l1_alignment,
    mean_vec,
    signature_vec,
    vec_from_mapping,
)

_wp = _writing_prefs()
FRAGMENT_TYPES = _wp.FRAGMENT_TYPES
DIMENSIONS = _wp.DIMENSIONS

_EVAL_DIR = Path(__file__).resolve().parent / "exemplars_holdout"

SPLIT_VERSION = "work-v2"
TRAIN_WORKS = frozenset({"孔乙己", "故乡", "药", "铸剑"})
HOLDOUT_WORKS = frozenset(
    {
        "祝福",
        "阿Q正传",
        "春风沉醉的晚上",
        "从百草园到三味书屋",
        "社戏",
        "奔月",
        "伤逝",
        "在酒楼上",
        "肥皂",
        "明天",
    }
)
HOLDOUT_N_MIN = 4
THIN_OK_FRAGMENTS = frozenset({"battle_action"})

JINJIUYE_PROBE = (
    "「金九爷的案子，最后会怎样？」她问。\n\n"
    "「不知道。」\n\n"
    "「你不是最会算吗？」\n\n"
    "「人心没有账。」"
)


def split_of_work(work: str) -> str | None:
    name = (work or "").strip()
    if name in TRAIN_WORKS:
        return "train"
    if name in HOLDOUT_WORKS:
        return "holdout"
    return None


def merge_banks(*banks: dict[str, tuple[Exemplar, ...]]) -> dict[str, tuple[Exemplar, ...]]:
    out: dict[str, list[Exemplar]] = {}
    seen: set[tuple[str, str]] = set()
    for bank in banks:
        for samples in bank.values():
            for sample in samples:
                key = (sample.fragment, sample.slug)
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(sample.fragment, []).append(sample)
    return {k: tuple(v) for k, v in out.items()}


def load_eval_holdout_exemplars() -> dict[str, tuple[Exemplar, ...]]:
    """Passages used only for the holdout report. Not the live prototype bank."""
    bank = load_exemplars_dir(_EVAL_DIR, scope="holdout_eval")
    bad: list[str] = []
    for samples in bank.values():
        for sample in samples:
            if sample.work in TRAIN_WORKS or split_of_work(sample.work) != "holdout":
                bad.append(sample.work)
    if bad:
        raise ValueError(f"eval holdout works must be registered holdout (not train): {sorted(set(bad))}")
    return bank


def load_holdout_eval_bank() -> dict[str, tuple[Exemplar, ...]]:
    """Live bank ∪ eval-only holdout. Train still comes only from live-bank works."""
    return merge_banks(load_platform_exemplars(), load_eval_holdout_exemplars())


def filter_exemplars(
    bank: dict[str, tuple[Exemplar, ...]] | None = None,
    *,
    split: str,
) -> dict[str, tuple[Exemplar, ...]]:
    if split not in {"train", "holdout"}:
        raise ValueError(f"split must be train|holdout, got {split!r}")
    allowed = TRAIN_WORKS if split == "train" else HOLDOUT_WORKS
    src = bank if bank is not None else load_platform_exemplars()
    out: dict[str, tuple[Exemplar, ...]] = {}
    for frag, samples in src.items():
        kept = tuple(s for s in samples if s.work in allowed)
        if kept:
            out[frag] = kept
    return out


def unlabeled_works(bank: dict[str, tuple[Exemplar, ...]] | None = None) -> list[str]:
    src = bank if bank is not None else load_platform_exemplars()
    found: set[str] = set()
    for samples in src.values():
        for sample in samples:
            if split_of_work(sample.work) is None:
                found.add(sample.work)
    return sorted(found)


def _mean_signature(samples: tuple[Exemplar, ...]) -> dict[str, float]:
    if not samples:
        return {k: 0.0 for k in SIGNATURE_KEYS}
    vec = mean_vec(tuple(s.signature for s in samples))
    return {k: float(v) for k, v in zip(SIGNATURE_KEYS, vec)}


def _abs_delta(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {k: round(abs(float(a.get(k) or 0.0) - float(b.get(k) or 0.0)), 4) for k in SIGNATURE_KEYS}


def _composite_no_align(scored: dict[str, Any]) -> float | None:
    dims = scored.get("dimensions") or {}
    weights = scored.get("dimension_weights") or {}
    num = 0.0
    den = 0.0
    for dim in DIMENSIONS:
        if dim == "exemplar_alignment":
            continue
        w = float(weights.get(dim, 0.0))
        num += w * float(dims.get(dim, 0.0))
        den += w
    if den <= 0:
        return None
    return round(num / den, 4)


def _score_set(samples: tuple[Exemplar, ...], *, prefs: dict[str, Any]) -> dict[str, float | None]:
    if not samples:
        return {
            "composite": None,
            "composite_no_align": None,
            "alignment": None,
            "net_signal": None,
        }
    comps: list[float] = []
    comps_na: list[float] = []
    aligns: list[float] = []
    nets: list[float] = []
    for sample in samples:
        out = score_writing_fragment(
            sample.text,
            fragment_declared=sample.fragment,
            prefs=prefs,
        )
        comps.append(float(out["composite"]))
        na = _composite_no_align(out)
        if na is not None:
            comps_na.append(na)
        aligns.append(float((out.get("dimensions") or {}).get("exemplar_alignment") or 0.0))
        nets.append(float(out["net_signal"]))

    def _mean(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    return {
        "composite": _mean(comps),
        "composite_no_align": _mean(comps_na),
        "alignment": _mean(aligns),
        "net_signal": _mean(nets),
    }


def summarize_holdout(
    *,
    prefs: dict[str, Any] | None = None,
    bank: dict[str, tuple[Exemplar, ...]] | None = None,
) -> dict[str, Any]:
    """Train vs holdout signature/composite report. Does not write prefs."""
    src = bank if bank is not None else load_holdout_eval_bank()
    unknown = unlabeled_works(src)
    if unknown:
        raise ValueError(f"exemplar works not in train|holdout split: {unknown}")
    probe_prefs = prefs if prefs is not None else _wp.platform_prefs_payload()
    train_bank = filter_exemplars(src, split="train")
    hold_bank = filter_exemplars(src, split="holdout")
    fragments: dict[str, Any] = {}
    gate_ok = True
    for frag in FRAGMENT_TYPES:
        train = train_bank.get(frag, ())
        hold = hold_bank.get(frag, ())
        train_mean = _mean_signature(train)
        hold_mean = _mean_signature(hold)
        delta = _abs_delta(train_mean, hold_mean) if train and hold else {k: None for k in SIGNATURE_KEYS}
        mean_abs = None
        if train and hold:
            mean_abs = round(sum(float(v) for v in delta.values()) / len(SIGNATURE_KEYS), 4)
        train_scores = _score_set(train, prefs=probe_prefs)
        hold_scores = _score_set(hold, prefs=probe_prefs)
        n_hold = len(hold)
        thin = n_hold < HOLDOUT_N_MIN
        if thin and frag not in THIN_OK_FRAGMENTS:
            gate_ok = False
        fragments[frag] = {
            "n_train": len(train),
            "n_holdout": n_hold,
            "n_holdout_live": sum(1 for s in hold if s.scope == "platform"),
            "n_holdout_eval": sum(1 for s in hold if s.scope == "holdout_eval"),
            "thin": thin,
            "slugs_train": [s.slug for s in train],
            "slugs_holdout": [s.slug for s in hold],
            "train_mean": train_mean,
            "holdout_mean": hold_mean,
            "abs_delta": delta,
            "mean_abs_delta": mean_abs,
            "train_composite": train_scores["composite"],
            "holdout_composite": hold_scores["composite"],
            "train_composite_no_align": train_scores["composite_no_align"],
            "holdout_composite_no_align": hold_scores["composite_no_align"],
            "train_alignment": train_scores["alignment"],
            "holdout_alignment": hold_scores["alignment"],
            "train_net": train_scores["net_signal"],
            "holdout_net": hold_scores["net_signal"],
        }

    dialogue_train = train_bank.get("dialogue_dyad", ())
    probe_sig = extract_signature(JINJIUYE_PROBE)
    probe_align = None
    if dialogue_train:
        probe_align = l1_alignment(
            signature_vec(JINJIUYE_PROBE),
            vec_from_mapping(_mean_signature(dialogue_train)),
        )
    return {
        "split_version": SPLIT_VERSION,
        "schema_id": _wp.FEATURE_SCHEMA_ID,
        "train_works": sorted(TRAIN_WORKS),
        "holdout_works": sorted(HOLDOUT_WORKS),
        "holdout_gate": {
            "min_n": HOLDOUT_N_MIN,
            "thin_ok_fragments": sorted(THIN_OK_FRAGMENTS),
            "passed": gate_ok,
        },
        "fragments": fragments,
        "probe": {
            "id": "jinjiuye_dyad",
            "fragment": "dialogue_dyad",
            "gold": False,
            "l1_alignment_to_train": probe_align,
            "signature": probe_sig,
        },
    }
