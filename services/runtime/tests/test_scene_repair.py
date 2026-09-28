"""微场景重建：证据窗、工作单、本地复检。"""

from app.writing.scene_repair import projection_for_model, verify_scene_rebuild
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.scorer import score_writing_fragment

platform_prefs_payload = _writing_prefs().platform_prefs_payload

_LADDER = "\n".join(
    [
        "「你爸呢？」",
        "「医院。」",
        "「什么时候？」",
        "「昨晚。」",
        "「谁送的？」",
        "「老李。」",
        "「哪个老李？」",
        "「卖鱼的。」",
    ]
)


def test_interview_span_keeps_the_scene_facts_not_the_pings() -> None:
    prefs = platform_prefs_payload()
    text = (
        "陈小满来借三百块钱，他父亲昨晚摔伤，人还在医院。"
        "老李送来一批药材，是别人托他送来的，陈小满不知道托付者，药材还在车里。\n"
        + _LADDER
        + "\n\n第二天，江照把药材搬进后院。\n"
    )
    out = score_writing_fragment(text, fragment_declared="dialogue_dyad", prefs=prefs)
    span = out["repair_span"]
    assert span["repair_mode"] == "scene_rebuild"
    assert span["subtype"] == "interview"
    assert span["scene_problem"] == "authorial_information_exchange"
    assert "卖鱼的" in span["old_text"]
    assert "借三百" in span["old_text"]
    assert "第二天" not in span["old_text"]
    assert "evidence" not in span
    assert len(projection_for_model(span)["rewrite_contract"]) == 5
    assert out["telemetry_repair_span"]["evidence"]["interview"] >= 4
    brief = span["scene_repair_brief"]
    assert "信息问答" in brief["current_problem"]
    assert "逐条记录" in brief["current_problem"]
    assert "信息顺序" in brief["rewrite_target"]
    assert brief["rewrite_intent"] == "restore_normal_prose_granularity"
    shown = projection_for_model(span)
    assert "不要逐条重写原问题" in shown["subtype_instruction"]
    assert "事实下限" in "".join(shown["rewrite_contract"])
    assert "逐条写作清单" in shown["scene_repair_brief"]["preserve_note"]
    assert "rewrite_target" in shown["scene_repair_brief"]
    assert "先写人物正在处理" not in "".join(shown["rewrite_contract"])
    assert "rewrite_intent" not in shown["scene_repair_brief"]
    assert "scene_facts" not in shown["scene_repair_brief"]
    assert "信息密度" not in "".join(shown["rewrite_contract"])
    assert "scene_job" not in brief
    assert "scene_context" not in brief
    preserve = brief["preserve"]
    assert 1 <= len(preserve) <= 6
    assert any("三百" in item for item in preserve)
    assert any("药材" in item for item in preserve)
    assert any("老李" in item and "托" in item for item in preserve)
    assert "卖鱼的" not in preserve
    records = brief["scene_facts"]
    borrowed = next(item for item in records if item.get("action") == "借")
    assert borrowed["subject"] == "陈小满"
    assert "三百" in "".join(borrowed["anchors"]["object"])


def test_scene_job_comes_only_from_the_given_goal() -> None:
    prefs = platform_prefs_payload()
    goal = "陈小满来借钱，江照接触到一批来路异常的药材。"
    out = score_writing_fragment(
        _LADDER,
        fragment_declared="dialogue_dyad",
        prefs=prefs,
        scene_goal=goal,
    )
    brief = out["repair_span"]["scene_repair_brief"]
    assert brief["scene_context"] == {"type": "context", "text": goal}
    assert "scene_job" not in brief
    assert "state_change" not in brief
    shown = projection_for_model(out["repair_span"])
    assert shown["scene_repair_brief"]["scene_context"] == goal
    assert "不是本次重写必须完成的任务" in shown["scene_repair_brief"]["scene_context_note"]
    assert "scene_job" not in shown["scene_repair_brief"]


def test_rebuild_accepts_denser_exchange_and_rejects_a_new_template() -> None:
    old = _LADDER
    rebuilt = (
        "陈小满把湿袖口拧了拧：「先说我爸。昨晚摔的，老李送去医院，卖鱼的那个。」"
    )
    ok = verify_scene_rebuild(
        old,
        rebuilt,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "昨晚", "老李", "卖鱼的"],
    )
    assert ok["accepted"] is True
    assert ok["target_defect_reduced"] is True
    assert ok["after"] < ok["before"]
    assert ok["after"] < 4

    below_gate = "\n".join(
        [
            "父亲在医院，昨晚的事老李经手，卖鱼的那个，钱是三百。",
            "「谁？」",
            "「老李。」",
            "「哪个？」",
        ]
    )
    softened = verify_scene_rebuild(
        old,
        below_gate,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "昨晚", "老李", "卖鱼的", "三百"],
    )
    assert softened["accepted"] is True
    assert softened["after"] < 4
    assert softened["after"] > 0

    still_a_ladder = "\n".join(
        [
            "江照把三百交给他，人还在医院，昨晚的事是老李和卖鱼的经手的。",
            "「谁送的？」",
            "「老李。」",
            "「哪个？」",
            "「卖鱼的。」",
            "「为什么？」",
            "「托他。」",
            "「东西呢？」",
            "「车里。」",
        ]
    )
    partial = verify_scene_rebuild(
        old,
        still_a_ladder,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "三百", "老李", "卖鱼的"],
    )
    assert partial["accepted"] is False
    assert partial["reason"] == "target defect barely changed"

    swapped = "\n".join(
        [
            "「钟不知道，屋子知道。」",
            "「布就是锁。」",
            "「是包，不是我。」",
            "「小时候也这样，未必做得到。」",
        ]
    )
    bad = verify_scene_rebuild(
        old,
        swapped,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "昨晚", "老李", "卖鱼的"],
    )
    assert bad["accepted"] is False
    assert "previous" not in bad["reason"]
    assert bad["reason"]

    barely = "\n".join(
        [
            "「先把钱放下。」",
            "「三百。」",
            "「人在医院。」",
            "「昨晚的事。」",
            "「老李送的。」",
            "「卖鱼的那个。」",
        ]
    )
    not_reflowed = verify_scene_rebuild(
        old,
        barely,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "三百", "老李", "卖鱼的", "昨晚"],
    )
    assert not_reflowed["target_defect_reduced"] is True
    assert not_reflowed["accepted"] is False
    assert not_reflowed["reason"] == "prose not reflowed"

    exposition = (
        "江照询问了陈小满父亲的情况，陈小满回答说父亲昨晚摔伤，"
        "目前正在医院，是卖鱼的老李送去的，需要三百。"
    )
    flattened = verify_scene_rebuild(
        old,
        exposition,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "昨晚", "老李", "卖鱼的", "三百"],
    )
    assert flattened["accepted"] is False
    assert flattened["reason"] == "dialogue rewritten as exposition"

    still_mapped = "\n".join(
        [
            "「你父亲怎么样？」陈小满回答说他人在医院。",
            "「什么时候去的？」江照问。",
            "「昨晚。」",
            "江照又问谁送的。陈小满说是老李。",
            "至于哪个，他只说是卖鱼的。",
        ]
    )
    mapped = verify_scene_rebuild(
        old,
        still_mapped,
        key="staccato_uniform",
        subtype="interview",
        preserve=["医院", "昨晚", "老李", "卖鱼的"],
    )
    assert mapped["target_defect_reduced"] is True
    assert mapped["accepted"] is False
    assert mapped["reason"] == "prose not reflowed"

    from app.writing.scene_repair import scene_fact_records

    long_old = (
        "陈小满来借三百块钱，他父亲昨晚摔伤，人还在医院。"
        "老李送来一批药材，是别人托他送来的，陈小满不知道托付者，药材还在车里。"
        + ("他在门口站了一会儿，雨水顺着檐滴下来。" * 8)
        + "\n"
        + old
    )
    squeezed = "陈小满进门就说：「先给我三百。」药材的事没再提。"
    compressed = verify_scene_rebuild(
        long_old,
        squeezed,
        key="staccato_uniform",
        subtype="interview",
        preserve=scene_fact_records(long_old),
    )
    assert compressed["accepted"] is False
    assert compressed["reason"] == "destructive compression"
    paraphrased = verify_scene_rebuild(
        "陈小满来借三百块钱。\n" + old,
        "陈小满把外套放下：「给我三百。」他说得很快。",
        key="staccato_uniform",
        subtype="interview",
        preserve=scene_fact_records("陈小满来借三百块钱。"),
    )
    assert paraphrased["fact_change"] is False


def test_other_subtypes_only_forbid_the_old_organization() -> None:
    samples = {
        "quote_run": "逐拍拆开",
        "phatic": "应声",
        "logistics": "机械封场",
        "thesis": "公式化收束",
        "explicit_turn_chain": "发现",
        "institution_before_place": "开头先介绍机构",
        "years_ago_summary": "提要",
    }
    for subtype, needle in samples.items():
        shown = projection_for_model(
            {"subtype": subtype, "old_text": "x", "scene_repair_brief": {}}
        )
        text = shown["subtype_instruction"]
        assert needle in text
        assert "要加动作" not in text
        assert "信息差" not in text
        assert "文学感" not in text


def test_second_failure_is_carried_on_the_brief() -> None:
    prefs = platform_prefs_payload()
    out = score_writing_fragment(
        _LADDER,
        fragment_declared="dialogue_dyad",
        prefs=prefs,
        prior={"repair_feedback": {"reason": "target defect barely changed"}},
    )
    brief = out["repair_span"]["scene_repair_brief"]
    assert brief["previous_repair_failed"] == "target defect barely changed"
    assert "重新安排整场" in brief["retry_note"]
