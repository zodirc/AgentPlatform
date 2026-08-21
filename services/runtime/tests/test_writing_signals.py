from __future__ import annotations

import importlib.util
from pathlib import Path

_WP = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "python"
    / "agent_contracts"
    / "writing_prefs.py"
)
_spec = importlib.util.spec_from_file_location("agent_contracts.writing_prefs", _WP)
assert _spec and _spec.loader
_wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wp)

FRAGMENT_TYPES = _wp.FRAGMENT_TYPES
merge_prefs = _wp.merge_prefs
normalize_fragment = _wp.normalize_fragment
normalize_row = _wp.normalize_row
platform_prefs_payload = _wp.platform_prefs_payload
validate_fragment_weights = _wp.validate_fragment_weights


def test_normalize_fragment_unknown_to_mixed() -> None:
    assert normalize_fragment("dialogue_dyad") == "dialogue_dyad"
    assert normalize_fragment("not_a_type") == "mixed"


def test_platform_prefs_has_all_fragments() -> None:
    prefs = platform_prefs_payload()
    for frag in FRAGMENT_TYPES:
        row = prefs["fragment_weights"][frag]
        assert abs(sum(row.values()) - 1.0) < 0.02


def test_validate_fragment_weights_rejects_missing() -> None:
    import pytest

    with pytest.raises(ValueError, match="missing"):
        validate_fragment_weights({"dialogue_dyad": normalize_row({"structure": 1})})


def test_merge_prefs_keeps_stored_signals_not_weights() -> None:
    stored = {
        "preset_label": "custom",
        "fragment_weights": {
            f: normalize_row(
                {
                    "structure": 0.9,
                    "character": 0.025,
                    "pacing": 0.025,
                    "voice": 0.025,
                    "exemplar_alignment": 0.025,
                }
            )
            for f in FRAGMENT_TYPES
        },
        "signal_penalties": {"dialogue_dyad": {"staccato_uniform": 0.0}},
        "signal_rewards": {},
    }
    merged = merge_prefs(stored)
    assert merged["preset_label"] == "custom"
    platform = platform_prefs_payload()
    assert merged["fragment_weights"]["dialogue_dyad"] == platform["fragment_weights"]["dialogue_dyad"]
    assert merged["signal_penalties"]["dialogue_dyad"]["staccato_uniform"] == 0.0


def test_apply_style_leans_zeros_unselected() -> None:
    penalties, rewards = _wp.apply_style_leans(["dialogue_dyad"])
    assert penalties["dialogue_dyad"]["staccato_uniform"] < 0
    assert penalties["battle_action"]["staccato_uniform"] == 0.0
    assert rewards["battle_action"]["exemplar_alignment_high"] == 0.0


def test_apply_style_gains_scales_rows() -> None:
    penalties, rewards = _wp.apply_style_gains({"dialogue_dyad": 0.5, "battle_action": 0.0})
    full = _wp.PLATFORM_SIGNAL_PENALTIES["staccato_uniform"]
    assert abs(penalties["dialogue_dyad"]["staccato_uniform"] - full * 0.5) < 1e-6
    assert penalties["battle_action"]["staccato_uniform"] == 0.0
    assert rewards["dialogue_dyad"]["exemplar_alignment_high"] == round(
        _wp.PLATFORM_SIGNAL_REWARDS["exemplar_alignment_high"] * 0.5, 4
    )
    inferred = _wp.infer_style_gains(penalties, rewards)
    assert abs(inferred["dialogue_dyad"] - 0.5) < 0.02
    assert inferred["battle_action"] == 0.0


from app.writing.signals.bank import load_platform_exemplars
from app.writing.signals.fit import exemplars_score_high
from app.writing.signals.fragments import detect_fragment
from app.writing.signals.scorer import score_writing_fragment
from app.writing.signals.signature import FEATURE_SCHEMA_ID, SIGNATURE_KEYS, mean_vec, prototype_alignment
from app.writing.signals.space import fit_signature, load_platform_space


def test_detect_dialogue_fragment() -> None:
    text = "\n".join([f"「一句对白 número {i}？」" for i in range(8)])
    assert detect_fragment(text) == "dialogue_dyad"


def test_score_writing_fragment_has_signals_block() -> None:
    prefs = platform_prefs_payload()
    text = "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台。" * 3
    out = score_writing_fragment(
        text,
        fragment_declared="worldview_texture",
        section_id="ch1",
        prefs=prefs,
    )
    assert "dimensions" in out
    assert "penalties" in out
    assert "rewards" in out
    assert 0.0 <= out["composite"] <= 1.0
    assert 0.0 <= out["net_signal"] <= 1.0
    assert out["fragment"]["declared"] == "worldview_texture"
    assert out["exemplar_fit"]["n"] >= 1
    assert out["exemplar_fit"]["schema_id"] == FEATURE_SCHEMA_ID
    assert set(out["exemplar_fit"]["signature"]) == set(SIGNATURE_KEYS)
    nearest = out["exemplar_fit"]["nearest"]
    assert nearest["author"] == "鲁迅"
    assert nearest["work"]
    assert out["rewrite_policy"] in {"draft_ok", "propose_patch"}


def test_exemplar_bank_covers_all_fragments() -> None:
    bank = load_platform_exemplars()
    catalog = _wp.EXEMPLAR_CATALOG
    for frag in FRAGMENT_TYPES:
        assert frag in bank and len(bank[frag]) >= 4, frag
        titles = {(s.author, s.work, s.beat) for s in bank[frag]}
        for entry in catalog[frag]:
            assert (entry["author"], entry["work"], entry["beat"]) in titles, entry
    space = load_platform_space()
    for frag in FRAGMENT_TYPES:
        proto = space.prototype(frag)
        assert proto is not None and proto.n >= 4


def test_exemplar_self_alignment_is_high() -> None:
    bank = load_platform_exemplars()
    sample = bank["battle_action"][0]
    own = fit_signature(sample.text, "battle_action")["score"]
    other = fit_signature(sample.text, "dialogue_dyad")["score"]
    assert own > other
    assert own >= 0.65


def test_score_is_distance_to_prototype_not_max_sample() -> None:
    space = load_platform_space()
    proto = space.prototype("worldview_texture")
    assert proto is not None and proto.n >= 2
    centroid_score = prototype_alignment(
        proto.neighbors[0].signature,
        proto.centroid,
        proto.scale,
        n=proto.n,
    )
    assert centroid_score < 0.999
    rebuilt = mean_vec(tuple(s.signature for s in proto.neighbors))
    assert rebuilt == proto.centroid


def test_staccato_dialogue_fits_worse_than_yudafu() -> None:
    bank = load_platform_exemplars()
    yudafu = next(s for s in bank["dialogue_dyad"] if s.author == "郁达夫")
    telegraph = "\n".join(["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"] * 4)
    good = fit_signature(yudafu.text, "dialogue_dyad")["score"]
    bad = fit_signature(telegraph, "dialogue_dyad")["score"]
    assert good > bad


def test_own_class_beats_other_class() -> None:
    bank = load_platform_exemplars()
    texture = bank["worldview_texture"][0].text
    own = fit_signature(texture, "worldview_texture")["score"]
    other = fit_signature(texture, "battle_action")["score"]
    assert own > other


def test_exemplars_fit_the_evaluator() -> None:
    failures = exemplars_score_high(min_net=0.50)
    assert failures == [], failures


def test_dialogue_rewards_encourage_exemplar_not_telegraph() -> None:
    bank = load_platform_exemplars()
    yudafu = next(s for s in bank["dialogue_dyad"] if s.author == "郁达夫")
    prefs = platform_prefs_payload()
    good = score_writing_fragment(
        yudafu.text, fragment_declared="dialogue_dyad", prefs=prefs
    )
    telegraph = "\n".join(["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"] * 4)
    bad = score_writing_fragment(
        telegraph, fragment_declared="dialogue_dyad", prefs=prefs
    )
    good_keys = {r["key"] for r in good["rewards"]}
    bad_keys = {r["key"] for r in bad["rewards"]}
    assert "dialogue_rhythm_varied" in good_keys
    assert "dialogue_rhythm_varied" not in bad_keys
    assert "staccato_uniform" in {p["key"] for p in bad["penalties"]}
    assert good["exemplar_fit"]["score"] > bad["exemplar_fit"]["score"]
    assert good["net_signal"] > bad["net_signal"]
    assert "outline_duty_match" not in good_keys
    assert bad["net_signal"] < 0.80


def test_ledger_telegraph_is_penalized_like_staccato() -> None:
    bank = load_platform_exemplars()
    yudafu = next(s for s in bank["dialogue_dyad"] if s.author == "郁达夫")
    prefs = platform_prefs_payload()
    good = score_writing_fragment(
        yudafu.text, fragment_declared="dialogue_dyad", prefs=prefs
    )
    ledger = "\n\n".join(
        ["「进来拿。」", "「我会还。」", "「先记账。」", "「记多久？」"]
    )
    bad = score_writing_fragment(
        ledger, fragment_declared="dialogue_dyad", prefs=prefs
    )
    assert "staccato_uniform" in {p["key"] for p in bad["penalties"]}
    assert "dialogue_rhythm_varied" not in {r["key"] for r in bad["rewards"]}
    assert good["net_signal"] > bad["net_signal"]
    assert bad["net_signal"] < 0.55


def test_split_speech_and_contrast_punch_are_penalized() -> None:
    prefs = platform_prefs_payload()
    split = score_writing_fragment(
        "「你家。」他说，「你袖口那块布，就是锁。」",
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    punch = score_writing_fragment(
        "「不在了。」\n「你怎么知道？」\n「他来找的是包，不是我。」",
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    equate = score_writing_fragment(
        "「你袖口那块布，就是锁。」",
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    antithesis = score_writing_fragment(
        "「电池还能撑一阵。」他擦了擦玻璃。\n「钟不知道，屋子知道。」他说。",
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    because = score_writing_fragment(
        "「他来找包，因为只问包在哪。」她把灯芯拨正，油烟贴在碗沿上。" * 3,
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    assert "staccato_uniform" in {p["key"] for p in split["penalties"]}
    assert "staccato_uniform" in {p["key"] for p in punch["penalties"]}
    assert "staccato_uniform" in {p["key"] for p in equate["penalties"]}
    assert "staccato_uniform" in {p["key"] for p in antithesis["penalties"]}
    assert "staccato_uniform" not in {p["key"] for p in because["penalties"]}
    assert "dialogue_rhythm_varied" not in {r["key"] for r in split["rewards"]}
    assert "dialogue_rhythm_varied" not in {r["key"] for r in punch["rewards"]}
    assert split["net_signal"] < because["net_signal"]
    assert punch["net_signal"] < because["net_signal"]
    assert equate["net_signal"] < because["net_signal"]
    assert antithesis["net_signal"] < because["net_signal"]


def test_live_prefs_do_not_mask_exemplar_penalties() -> None:
    from app.writing.signals.fit import fit_signal_penalties

    masked = fit_signal_penalties()
    platform = platform_prefs_payload()["signal_penalties"]
    for frag in FRAGMENT_TYPES:
        for key, val in platform[frag].items():
            assert masked[frag][key] == val, (frag, key, masked[frag][key], val)


def test_exemplars_earn_alignment_and_avoid_mismatch() -> None:
    bank = load_platform_exemplars()
    prefs = platform_prefs_payload()
    n = 0
    align_hits = 0
    mismatch_hits = 0
    shown_hits = 0
    for frag, samples in bank.items():
        for sample in samples:
            n += 1
            out = score_writing_fragment(
                sample.text, fragment_declared=frag, prefs=prefs
            )
            keys_r = {r["key"] for r in out["rewards"]}
            keys_p = {p["key"] for p in out["penalties"]}
            assert out["dimensions"]["exemplar_alignment"] >= 0.65, sample.slug
            assert out["dimensions"]["voice"] < 0.99, sample.slug
            if "exemplar_alignment_high" in keys_r:
                align_hits += 1
            if "fragment_mismatch" in keys_p:
                mismatch_hits += 1
            if "scene_ratio_high" in keys_r:
                shown_hits += 1
    assert n == 24
    assert mismatch_hits == 0
    assert align_hits >= 18
    assert shown_hits >= 16


def test_anti_patterns_score_below_class_exemplars() -> None:
    bank = load_platform_exemplars()
    prefs = platform_prefs_payload()
    controls = {
        "dialogue_dyad": (
            "telegraph",
            "\n".join(["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"] * 4),
        ),
        "worldview_texture": (
            "lore",
            "本章先交代世界观。帝国分三省，魔法源于古神血脉。"
            "主角名叫林晓，幼年父母双亡，体内有神秘力量。"
            "他心里清楚自己必须变强，于是决定踏上旅程。",
        ),
        "climax_beat": (
            "slogan",
            "终于到了这一刻。所有的铺垫都在这一章爆发。他大喊一声，命运就此改变。然后他赢了。",
        ),
        "plot_progress": (
            "hinge",
            "他看见桌上的刀，立刻明白了。他听到门外脚步，立刻拧身。"
            "他看到血，立刻冲出去。他听见喊声，立刻拔刀。柜台上还温着酒。" * 2,
        ),
            "battle_action": (
                "count",
                ("他拔刀。他冲。他斩。他再冲。他再斩。" * 6)
                + "刀光一闪，敌人倒了。然后他赢了。",
            ),
    }
    for frag, (name, text) in controls.items():
        exemplars = [
            score_writing_fragment(s.text, fragment_declared=frag, prefs=prefs)["net_signal"]
            for s in bank[frag]
        ]
        floor = min(exemplars)
        bad = score_writing_fragment(text, fragment_declared=frag, prefs=prefs)
        assert bad["net_signal"] < floor, (frag, name, bad["net_signal"], floor, bad)
        assert bad["net_signal"] < 0.70, (frag, name, bad["net_signal"], bad)


def test_detect_cast_sword_as_battle() -> None:
    bank = load_platform_exemplars()
    sample = next(s for s in bank["battle_action"] if "青剑" in s.slug or "青剑" in s.beat)
    assert detect_fragment(sample.text) in {"battle_action", "mixed", "plot_progress"}
    prefs = platform_prefs_payload()
    out = score_writing_fragment(
        sample.text, fragment_declared="battle_action", prefs=prefs
    )
    assert out["fragment"]["mismatch"] is False
    assert "exemplar_alignment_high" in {r["key"] for r in out["rewards"]}


def test_nested_signal_lookup_zero_disables() -> None:
    prefs = platform_prefs_payload()
    prefs["signal_penalties"]["dialogue_dyad"]["staccato_uniform"] = 0.0
    telegraph = "\n".join(["「跑完了？」", "「跑完了。」"] * 6)
    out = score_writing_fragment(
        telegraph,
        fragment_declared="dialogue_dyad",
        prefs=prefs,
    )
    assert not any(p["key"] == "staccato_uniform" for p in out["penalties"])


def test_is_prose_writing_path() -> None:
    from app.writing.signals.prose_path import is_prose_writing_path

    assert is_prose_writing_path("sections/01.md")
    assert is_prose_writing_path("drafts/manuscript.md")
    assert not is_prose_writing_path("outline.md")
    assert not is_prose_writing_path("README.md")


def test_maybe_attach_skips_outline(monkeypatch) -> None:
    from app.writing.signals.assemble import maybe_attach_prose_writing_signals

    async def _noop(*args, **kwargs):
        raise AssertionError("build_writing_signals should not run for outline")

    monkeypatch.setattr(
        "app.writing.signals.assemble.build_writing_signals",
        _noop,
    )

    result = {"status": "applied", "path": "outline.md", "new_text": "x" * 200}

    import asyncio

    asyncio.run(
        maybe_attach_prose_writing_signals(
            result,
            tool_name="propose_patch",
            arguments={"fragment": "mixed"},
        )
    )
    assert "writing_signals" not in result


def test_long_chapter_window_points_repair_span_at_staccato_island() -> None:
    prefs = platform_prefs_payload()
    texture = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人傍午散了工，花四文铜钱买一碗酒。\n\n"
    ) * 8
    island = "\n".join(
        ["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"] * 2
    )
    tail = (
        "只有穿长衫的，才踱进店面隔壁的房子里，要酒要菜，慢慢地坐喝。"
        "柜台上还温着酒，粉板上记着十九个钱。\n\n"
    ) * 6
    text = texture + island + "\n\n" + tail
    out = score_writing_fragment(
        text, fragment_declared="worldview_texture", prefs=prefs
    )
    assert out["windows"]["n"] >= 2
    assert out["rewrite_policy"] == "propose_patch"
    span = out["repair_span"]
    assert "跑完了" in span["old_text"]
    assert span["old_text"] in text
    assert span["key"] == "staccato_uniform"


def test_short_draft_allows_full_redraft_policy() -> None:
    prefs = platform_prefs_payload()
    text = "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台。"
    out = score_writing_fragment(
        text, fragment_declared="worldview_texture", prefs=prefs
    )
    assert out["rewrite_policy"] == "draft_ok"
    assert "windows" not in out


def test_infer_fragment_from_duty() -> None:
    from app.writing.signals.spec import infer_fragment_from_duty

    assert infer_fragment_from_duty("过日子，写铺子的规矩和价钱") == "worldview_texture"
    assert infer_fragment_from_duty("本章高潮，摊牌") == "climax_beat"
    assert infer_fragment_from_duty("加压，把主线往前推") == "plot_progress"
    assert infer_fragment_from_duty("铺垫章，不要假高潮") == "mixed"


def test_maybe_attach_scores_updated_chapter_not_span(workspace: Path) -> None:
    import asyncio
    import json

    from app.writing.manuscript import upsert_section
    from app.writing.signals.assemble import maybe_attach_prose_writing_signals
    from app.writing.signals.scorer import score_writing_fragment

    texture = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人傍午散了工，花四文铜钱买一碗酒。\n\n"
    ) * 8
    island = "\n".join(
        ["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"] * 2
    )
    tail = (
        "只有穿长衫的，才踱进店面隔壁的房子里，要酒要菜，慢慢地坐喝。"
        "柜台上还温着酒，粉板上记着十九个钱。\n\n"
    ) * 6
    chapter = texture + island + "\n\n" + tail
    new_span = "「你还在喘？」他靠着柜台说。"
    patched = chapter.replace("「跑完了？」", new_span, 1)
    doc = upsert_section("", "ch1", patched)
    doc = upsert_section(doc, "ch2", texture)
    drafts = workspace / "drafts"
    drafts.mkdir()
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    turn_id = "turn-patch-score"
    manifest = workspace / ".agent" / "work" / "turns" / f"{turn_id}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"section_drafts": {"ch1": {"fragment": "mixed"}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = {
        "status": "applied",
        "path": "drafts/manuscript.md",
        "old_text": "「跑完了？」",
        "new_text": new_span,
        "auto_applied": True,
    }
    asyncio.run(
        maybe_attach_prose_writing_signals(
            result,
            tool_name="propose_patch",
            arguments={
                "path": "drafts/manuscript.md",
                "fragment": "dialogue_dyad",
                "old_text": "「跑完了？」",
                "new_text": new_span,
            },
            turn_id=turn_id,
        )
    )
    signals = result.get("writing_signals") or {}
    assert result.get("section_id") == "ch1"
    vis = int((signals.get("length_fields") or {}).get("visible_chars") or 0)
    assert vis >= 800
    assert vis != len(new_span)
    assert signals.get("rewrite_policy") == "propose_patch"
    assert (signals.get("fragment") or {}).get("declared") == "mixed"
    span_only = score_writing_fragment(
        new_span, fragment_declared="dialogue_dyad", prefs=platform_prefs_payload()
    )
    assert span_only["rewrite_policy"] == "draft_ok"
    assert result.get("content") is None
    assert result.get("new_text") == new_span

