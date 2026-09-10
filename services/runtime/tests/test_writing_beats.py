from __future__ import annotations

from pathlib import Path

from app.writing.signals.beats import (
    format_local_beats_block,
    pick_promote_payload,
    write_local_beats,
)

_CLEARED_BEAT = (
    "她把香菜塞给我。秤上还沾着泥。我把筷子搁在碗沿上，说这里有床，"
    "走过去还要坐车。母亲没有再劝，只把灯拨亮了一点。门外有人喊收工钱，"
    "她应了一声，没有回头。灶上的汤还开着，我把火掣小，水花落下去。"
)


def test_is_writing_weak_quality_hits_still_patch() -> None:
    from app.writing.signals.repair import is_l0_weak, is_writing_weak

    assert is_writing_weak(
        net=0.83, penalties=[{"key": "staccato_uniform", "hit": True}]
    )
    assert not is_writing_weak(net=0.41, penalties=[])
    assert is_writing_weak(net=0.83, penalties=[], length_short=True)
    assert not is_writing_weak(
        net=0.83, penalties=[{"key": "meta_knowing_high", "hit": True}]
    )
    assert not is_writing_weak(
        net=0.72, penalties=[{"key": "glue_heavy", "hit": True}]
    )
    assert not is_l0_weak(
        net=0.83, penalties=[{"key": "meta_knowing_high", "hit": True}]
    )
    assert not is_writing_weak(net=0.83, penalties=[])


def test_pick_promote_requires_l0_then_clear() -> None:
    staccato = {
        "id": "e1",
        "section_id": "ch1",
        "fragment_declared": "mixed",
        "created_at": "2026-08-24T09:45:13Z",
        "writing_signals": {
            "net_signal": 0.45,
            "composite": 0.63,
            "penalties": [{"key": "staccato_uniform", "hit": True, "delta": -0.18}],
            "beat_window": {"text": "「听见没有？」我问。\n「听见了。」" * 8, "visible_chars": 200},
        },
    }
    cleared = {
        "id": "e3",
        "section_id": "ch1",
        "fragment_declared": "mixed",
        "created_at": "2026-08-24T09:45:36Z",
        "writing_signals": {
            "net_signal": 0.83,
            "composite": 0.82,
            "penalties": [{"key": "meta_knowing_high", "hit": True, "delta": -0.06}],
            "beat_window": {"text": _CLEARED_BEAT, "visible_chars": 140},
        },
    }
    picked = pick_promote_payload([staccato, cleared])
    assert picked is None
    clean = {
        "id": "e4",
        "section_id": "ch1",
        "fragment_declared": "mixed",
        "created_at": "2026-08-24T09:45:50Z",
        "writing_signals": {
            "net_signal": 0.91,
            "composite": 0.88,
            "penalties": [],
            "beat_window": {"text": _CLEARED_BEAT, "visible_chars": 140},
        },
    }
    picked = pick_promote_payload([staccato, cleared, clean])
    assert picked is not None
    assert picked["section_id"] == "ch1"
    assert "香菜" in picked["text"]
    assert picked["weight"] >= 0.5
    assert pick_promote_payload([cleared]) is None
    assert pick_promote_payload([clean]) is None


def test_same_span_without_composite_gain_is_unproductive() -> None:
    from app.writing.signals.repair import unproductive_repeat

    prior = {"composite": 0.83, "repair_span": {"old_text": "小屋还空着。", "key": "meta_knowing_high"}}
    span = {"old_text": "小屋还空着。", "key": "meta_knowing_high"}
    assert unproductive_repeat(prior, span, 0.83) is True
    assert unproductive_repeat(prior, span, 0.85) is True
    assert unproductive_repeat(prior, {"old_text": "另一处心里清楚。", "key": "meta_knowing_high"}, 0.83) is False


def test_peeled_same_island_is_unproductive() -> None:
    from app.writing.signals.repair import unproductive_repeat

    prior = {
        "repair_span": {
            "key": "meta_knowing_high",
            "old_text": "「你舅舅给你介绍的那个活，干了三年还只是抄表？」\n「先干着。」",
        }
    }
    peeled = {
        "key": "meta_knowing_high",
        "old_text": "电话那头问：「你舅舅给你介绍的那个活，干了三年还只是抄表？」",
    }
    assert unproductive_repeat(prior, peeled, 0.82) is True
    other = {
        "key": "staccato_uniform",
        "old_text": "工人问：「谁签字？」\n老孙说：「我。」",
    }
    assert unproductive_repeat(prior, other, 0.39) is False


def test_local_beats_go_in_volatile_after_spec(tmp_path: Path) -> None:
    from app.writing.cards import extract_cards_block, prepare_writing_system_prompt

    body = _CLEARED_BEAT
    write_local_beats(
        [{"fragment": "mixed", "section_id": "ch1", "text": body}],
        workspace_root=tmp_path,
    )
    block = format_local_beats_block("写一份生活的文章", workspace_root=tmp_path)
    assert block.startswith("## Local beats")
    assert "禁止搬情节" in block
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一份生活的文章",
        workspace_root=tmp_path,
    )
    assert "## Local beats" in pin.volatile_block
    spec_at = pin.volatile_block.find("## Writing spec")
    beats_at = pin.volatile_block.find("## Local beats")
    assert spec_at != -1 and beats_at != -1 and spec_at < beats_at
    assert "## Local beats" not in pin.prompt
    assert "Local beats" not in extract_cards_block(pin.volatile_block)


def test_new_piece_does_not_inject_prior_local_beats(tmp_path: Path) -> None:
    from app.writing.cards import prepare_writing_system_prompt

    write_local_beats(
        [{"fragment": "mixed", "section_id": "ch1", "text": _CLEARED_BEAT}],
        workspace_root=tmp_path,
    )
    assert format_local_beats_block("写一份生活的文章", workspace_root=tmp_path)
    assert format_local_beats_block("写一篇故事，民国风格", workspace_root=tmp_path) == ""
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一篇故事",
        workspace_root=tmp_path,
    )
    assert "## Local beats" not in pin.volatile_block
