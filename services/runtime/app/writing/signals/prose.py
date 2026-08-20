"""Prose-only metrics for writing_signals (not the docs/code rubric)."""

from __future__ import annotations

import re
from typing import Any

from app.writing.staccato import staccato_fields
from app.writing.text_metrics import visible_chars

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_DIALOGUE_OR_ACTION = re.compile(
    r'[「」『』“”"].+|说道|问道|答道|点了点头|摇了摇头|转身|推门|拔刀|拔枪'
)
_SYNOPSIS_CUE = re.compile(
    r"本章讲述|本章先|这一章|由此可见|概括|总结起来|总而言之|"
    r"到了这一刻|所有的铺垫|命运就此|踏上旅程"
)
_MOTION = re.compile(
    r"走|站|坐|跑|冲|咬|劈|拉|飞|缩|摸|递|喊|叫|望|进|来|去|喝|买|温|捧|塞|抢|射"
)
_BODY = re.compile(r"手|头|眼|脸|嘴|肩|脚|臂|鼻")
_PERSON = re.compile(r"他|她|我|你|们|说|道")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def paragraphs(text: str) -> list[str]:
    body = (text or "").strip()
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return parts or ([body] if body else [])


def sentence_count(text: str) -> int:
    return len([p for p in _SENT_SPLIT.split(text or "") if p.strip()])


def paragraph_shown(para: str) -> bool:
    if "「" in para and "」" in para:
        return True
    # Told-not-shown: 终于/本章/于是 without a spoken beat.
    if _SYNOPSIS_CUE.search(para):
        return False
    if _DIALOGUE_OR_ACTION.search(para):
        return True
    return bool(_MOTION.search(para) or _BODY.search(para))


def narrative_scene_ratio(text: str) -> float:
    paras = paragraphs(text)
    if not paras:
        return 0.0
    hits = sum(1.0 if paragraph_shown(p) else 0.0 for p in paras)
    syn = sum(0.5 for p in paras if _SYNOPSIS_CUE.search(p) and not ("「" in p and "」" in p))
    return round(_clamp((hits - syn) / len(paras)), 4)


def synopsis_rate(text: str) -> float:
    paras = paragraphs(text)
    if not paras:
        return 0.0
    n = sum(1 for p in paras if _SYNOPSIS_CUE.search(p) and not ("「" in p and "」" in p))
    return round(n / len(paras), 4)


def has_person_on_stage(text: str) -> bool:
    body = text or ""
    return bool(_PERSON.search(body) or ("「" in body and "」" in body))


def shown_for_fragment(fragment: str, *, scene: float, feats: dict[str, float]) -> bool:
    """Type-aware 'shown not told'. Dialogue is not required for texture/action."""
    quote = float(feats.get("quote_ratio") or 0.0)
    battle = float(feats.get("battle_density") or 0.0)
    world = float(feats.get("world_density") or 0.0)
    if fragment == "dialogue_dyad":
        return scene >= 0.45 and quote >= 0.20
    if fragment == "battle_action":
        return battle >= 0.12 or scene >= 0.40
    if fragment == "worldview_texture":
        return world >= 0.08 or (scene >= 0.35 and quote < 0.45)
    if fragment == "climax_beat":
        return scene >= 0.30
    if fragment == "plot_progress":
        return scene >= 0.25
    return scene >= 0.35


def anti_pattern_flags(text: str, rubric: dict[str, Any]) -> dict[str, bool]:
    from app.writing.hinge import hinge_fields

    staccato = bool(staccato_fields(text).get("staccato_uniform"))
    hinge = bool(hinge_fields(text).get("hinge_dense"))
    meta = float(rubric.get("meta_knowing_rate") or 0.0) >= 0.35
    glue = float(rubric.get("glue_rate") or 0.0) >= 0.35
    syn = synopsis_rate(text) >= 0.5
    return {
        "staccato": staccato,
        "hinge": hinge,
        "meta": meta,
        "glue": glue,
        "synopsis": syn,
    }


def character_card_action_hit(text: str) -> bool:
    body = (text or "").strip()
    if visible_chars(body) < 40:
        return False
    try:
        from app.writing.cards import load_writing_cards

        cards = [c for c in load_writing_cards() if c.kind == "character"]
    except Exception:
        return False
    if not cards:
        return False
    for card in cards:
        name = (card.title or "").strip()
        if len(name) >= 2 and name in body:
            return True
    return False
