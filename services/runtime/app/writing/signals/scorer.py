from __future__ import annotations

import re
from typing import Any

from app.writing.signals.prefs_loader import _module as _writing_prefs

_wp = _writing_prefs()
normalize_fragment = _wp.normalize_fragment
DIMENSIONS = _wp.DIMENSIONS
signal_coeff = _wp.signal_coeff
ALIGN_REWARD_FLOOR = float(_wp.ALIGN_REWARD_FLOOR)
MISMATCH_ALIGN_FLOOR = float(_wp.MISMATCH_ALIGN_FLOOR)

from app.offline.rubric import score_rubric
from app.writing.hinge import hinge_fields
from app.writing.lore import lore_fields
from app.writing.opening import opening_fields
from app.writing.outline_arc import outline_arc_fields
from app.writing.signals.fragments import detect_fragment
from app.writing.signals.prose import (
    anti_pattern_flags,
    character_card_action_hit,
    has_person_on_stage,
    narrative_scene_ratio,
    sentence_count,
    shown_for_fragment,
    synopsis_rate,
)
from app.writing.signals.space import MetricSpace, fit_signature
from app.writing.staccato import staccato_fields
from app.writing.text_metrics import draft_length_fields, visible_chars


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _dimension_scores(
    text: str,
    rubric: dict[str, Any],
    *,
    fragment_declared: str,
    space: MetricSpace | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Prose dimensions. Docs/code rubric style/structure are not used as-is."""
    vis = visible_chars(text)
    scene = narrative_scene_ratio(text)
    meta_rate = float(rubric.get("meta_knowing_rate") or 0.0)
    glue_rate = float(rubric.get("glue_rate") or 0.0)
    syn = synopsis_rate(text)
    flags = anti_pattern_flags(text, rubric)
    fit = fit_signature(text, fragment_declared, space=space)
    feats = fit.get("signature") or {}
    sent_cv = float(feats.get("sent_cv") or 0.0)
    n_sents = sentence_count(text)

    structure = 0.42
    if vis >= 80:
        structure += 0.12
    if vis >= 160:
        structure += 0.08
    if n_sents >= 2:
        structure += 0.10
    if n_sents >= 4:
        structure += 0.06
    structure -= 0.22 * syn
    if re_heading(text):
        structure -= 0.18
    structure = _clamp(structure)

    character = _clamp(
        0.50 * scene
        + 0.22 * (1.0 - meta_rate)
        + 0.18 * (1.0 if has_person_on_stage(text) else 0.0)
        + 0.10 * (1.0 - syn)
    )

    pacing = _clamp(0.40 * scene + 0.35 * sent_cv + 0.25 * (1.0 - glue_rate))
    if flags["staccato"]:
        pacing = _clamp(pacing - 0.28)
    if flags["hinge"]:
        pacing = _clamp(pacing - 0.16)

    voice = 0.48
    if vis >= 40:
        voice += 0.08
    ban_hits = rubric.get("ban_hits") or []
    if not ban_hits:
        voice += 0.10
    else:
        voice -= 0.12 * min(len(ban_hits), 3)
    voice += 0.18 * min(sent_cv, 1.0)
    voice -= 0.12 * min(meta_rate, 1.0)
    voice -= 0.08 * min(glue_rate, 1.0)
    voice -= 0.16 * syn
    if flags["staccato"]:
        voice -= 0.30
    if flags["hinge"]:
        voice -= 0.18
    voice = _clamp(voice)

    exemplar = float(fit.get("score") or 0.0)
    if flags["synopsis"]:
        exemplar *= 0.5
        voice = _clamp(voice - 0.10)
        character = _clamp(character - 0.12)
    if flags["staccato"]:
        exemplar *= 0.6
    if flags["hinge"]:
        exemplar *= 0.7
    if flags["meta"]:
        exemplar *= 0.7
    dims = {
        "structure": round(structure, 4),
        "character": round(character, 4),
        "pacing": round(pacing, 4),
        "voice": round(voice, 4),
        "exemplar_alignment": round(exemplar, 4),
    }
    return dims, fit


def re_heading(text: str) -> bool:
    return bool(re.search(r"^#{1,3}\s", text or "", re.M))


def _fragment_mismatch(
    *,
    declared: str,
    detected: str,
    alignment: float,
) -> bool:
    if declared == "mixed":
        return False
    if declared == detected:
        return False
    return float(alignment) < MISMATCH_ALIGN_FLOOR


def _collect_penalties(
    text: str,
    *,
    section_id: str,
    fragment_declared: str,
    fragment_detected: str,
    alignment: float,
    length_fields: dict[str, Any],
    prefs: dict[str, Any],
    skip_opening: bool = False,
) -> list[dict[str, Any]]:
    coeff = prefs.get("signal_penalties") or {}
    hits: list[dict[str, Any]] = []

    def add(key: str, hit: bool, hint: str) -> None:
        if not hit:
            return
        delta = signal_coeff(coeff, fragment_declared, key)
        if delta == 0.0:
            return
        hits.append({"key": key, "hit": True, "delta": round(delta, 4), "hint": hint})

    add("hinge_dense", bool(hinge_fields(text).get("hinge_dense")), "看见/听到后立马拧")
    add("staccato_uniform", bool(staccato_fields(text).get("staccato_uniform")), "对白过碎、拆句或「就是」收束")
    if not skip_opening:
        add(
            "opening_institution",
            bool(opening_fields(text, section_id).get("opening_institution")),
            "开篇机构专名",
        )
    add("lore_dump", bool(lore_fields(text, section_id).get("lore_dump")), "第一章身世提要")
    add("length_short", bool(length_fields.get("length_short")), "实体文字不足")
    rubric = score_rubric(text)
    add(
        "meta_knowing_high",
        float(rubric.get("meta_knowing_rate", 0)) >= 0.35,
        "元叙述/心里清楚过多",
    )
    add(
        "glue_heavy",
        float(rubric.get("glue_rate", 0)) >= 0.35,
        "连接词过密",
    )
    mismatch = _fragment_mismatch(
        declared=fragment_declared,
        detected=fragment_detected,
        alignment=alignment,
    )
    add(
        "fragment_mismatch",
        mismatch,
        f"申报 {fragment_declared} 与该类范本节奏不合（检测 {fragment_detected}）",
    )
    return hits


def _collect_rewards(
    text: str,
    *,
    section_id: str,
    fragment_declared: str,
    prefs: dict[str, Any],
    dimensions: dict[str, float],
    exemplar_fit: dict[str, Any],
) -> list[dict[str, Any]]:
    coeff = prefs.get("signal_rewards") or {}
    rubric = score_rubric(text)
    flags = anti_pattern_flags(text, rubric)
    feats = exemplar_fit.get("signature") or {}
    scene = narrative_scene_ratio(text)
    hits: list[dict[str, Any]] = []

    def add(key: str, hit: bool, hint: str) -> None:
        if not hit:
            return
        delta = signal_coeff(coeff, fragment_declared, key)
        if delta == 0.0:
            return
        hits.append({"key": key, "hit": True, "delta": round(delta, 4), "hint": hint})

    add(
        "scene_ratio_high",
        shown_for_fragment(fragment_declared, scene=scene, feats=feats)
        and not flags["staccato"]
        and not flags["hinge"]
        and not flags["synopsis"],
        "该类型该有的场面/质地在场上",
    )
    quote = float(feats.get("quote_ratio") or 0.0)
    add(
        "dialogue_rhythm_varied",
        quote >= 0.20 and scene >= 0.4 and not flags["staccato"],
        "对白节奏有变化",
    )
    align = float(dimensions.get("exemplar_alignment") or 0.0)
    add(
        "exemplar_alignment_high",
        align >= ALIGN_REWARD_FLOOR
        and not flags["staccato"]
        and not flags["hinge"]
        and not flags["meta"]
        and not flags["synopsis"],
        "接近该类型范本原型（节奏/质地，非情节）",
    )
    outline_md = ""
    if section_id:
        try:
            from app.tools.core.paths import _resolve_path

            op = _resolve_path("outline.md")
            if op.is_file():
                outline_md = op.read_text(encoding="utf-8")
        except OSError:
            outline_md = ""
    if outline_md:
        arc = outline_arc_fields(outline_md, section_id)
        add("outline_duty_match", not arc.get("outline_peak_flood"), "未抢高潮章职能")
    add(
        "character_card_action",
        character_card_action_hit(text),
        "人物卡姓名在场上行动",
    )
    return hits


def _score_span(
    text: str,
    *,
    fragment_declared: str,
    section_id: str = "",
    prefs: dict[str, Any],
    space: MetricSpace | None = None,
    skip_opening: bool = False,
    include_outline_rewards: bool = True,
) -> dict[str, Any]:
    declared = normalize_fragment(fragment_declared)
    detected = detect_fragment(text, space=space)
    rubric = score_rubric(text)
    length_fields = draft_length_fields(text, "")
    dimensions, exemplar_fit = _dimension_scores(
        text, rubric, fragment_declared=declared, space=space
    )
    weights = (prefs.get("fragment_weights") or {}).get(declared) or {}
    if not weights:
        weights = (prefs.get("fragment_weights") or {}).get("mixed") or {}

    composite = 0.0
    wsum = 0.0
    for dim in DIMENSIONS:
        w = float(weights.get(dim, 0.0))
        composite += w * float(dimensions.get(dim, 0.0))
        wsum += w
    composite = round(composite / wsum if wsum > 0 else sum(dimensions.values()) / len(dimensions), 4)

    alignment = float(dimensions.get("exemplar_alignment") or 0.0)
    mismatch = _fragment_mismatch(
        declared=declared, detected=detected, alignment=alignment
    )
    penalties = _collect_penalties(
        text,
        section_id=section_id,
        fragment_declared=declared,
        fragment_detected=detected,
        alignment=alignment,
        length_fields=length_fields,
        prefs=prefs,
        skip_opening=skip_opening,
    )
    rewards = _collect_rewards(
        text,
        section_id=section_id if include_outline_rewards else "",
        fragment_declared=declared,
        prefs=prefs,
        dimensions=dimensions,
        exemplar_fit=exemplar_fit,
    )
    net = composite + sum(p["delta"] for p in penalties) + sum(r["delta"] for r in rewards)
    net = round(max(0.0, min(1.0, net)), 4)

    return {
        "fragment": {
            "declared": declared,
            "detected": detected,
            "mismatch": mismatch,
        },
        "dimension_weights": {k: float(weights.get(k, 0.0)) for k in DIMENSIONS},
        "dimensions": dimensions,
        "penalties": penalties,
        "rewards": rewards,
        "composite": composite,
        "net_signal": net,
        "length_fields": length_fields,
        "exemplar_fit": exemplar_fit,
    }


def score_writing_fragment(
    text: str,
    *,
    fragment_declared: str,
    section_id: str = "",
    prefs: dict[str, Any],
    space: MetricSpace | None = None,
) -> dict[str, Any]:
    from app.writing.signals.repair import (
        WEAK_NET,
        build_repair_span,
        rewrite_policy_for,
    )
    from app.writing.signals.windows import split_score_windows
    from app.writing.text_metrics import visible_chars as vis_chars

    body = _score_span(
        text,
        fragment_declared=fragment_declared,
        section_id=section_id,
        prefs=prefs,
        space=space,
    )
    vis = vis_chars(text)
    length_short = bool((body.get("length_fields") or {}).get("length_short"))
    windows = split_score_windows(text)
    worst_win = None
    worst_scored: dict[str, Any] | None = None
    if len(windows) > 1:
        for i, win in enumerate(windows):
            scored = _score_span(
                win.text,
                fragment_declared=fragment_declared,
                section_id=section_id,
                prefs=prefs,
                space=space,
                skip_opening=i > 0,
                include_outline_rewards=False,
            )
            if worst_scored is None or float(scored["net_signal"]) < float(
                worst_scored["net_signal"]
            ):
                worst_win, worst_scored = win, scored
        if worst_scored is not None:
            body["net_signal"] = round(
                min(float(body["net_signal"]), float(worst_scored["net_signal"])),
                4,
            )
            body["windows"] = {
                "n": len(windows),
                "worst_net": worst_scored["net_signal"],
            }
            if worst_scored.get("penalties") and not body.get("penalties"):
                body["penalties"] = list(worst_scored["penalties"])

    probe_penalties = list(body.get("penalties") or [])
    if worst_scored is not None and (
        worst_scored.get("penalties")
        or float(body["net_signal"]) < WEAK_NET
    ):
        probe_penalties = list(worst_scored.get("penalties") or probe_penalties)
    span = build_repair_span(
        text,
        penalties=probe_penalties,
        window=worst_win,
        net_signal=float(body["net_signal"]),
    )
    if span:
        body["repair_span"] = span
    body["rewrite_policy"] = rewrite_policy_for(visible=vis, length_short=length_short)
    return body
