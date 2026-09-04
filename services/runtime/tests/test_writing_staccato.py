"""Uniform-short (staccato) facts + one-shot writing receipt."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.engine.state import TurnState
from app.engine.verify_receipt import (
    build_verify_receipt_text,
    mark_verify_receipt_injected,
    note_tool_result_for_verify,
    should_inject_verify_receipt,
    verify_receipt_kind,
)
from app.writing.staccato import (
    count_antithesis_punches,
    count_contrast_punches,
    count_echo_twists,
    count_equate_punches,
    count_identity_reasks,
    count_split_speech,
    count_thesis_mouth,
    find_staccato_span,
    max_duet_quote_run,
    max_interview_ladder,
    max_logistics_quote_run,
    max_short_quote_run,
    staccato_fields,
)


def _pad(body: str) -> str:
    return (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。\n\n"
    ) * 2 + body


def test_staccato_quote_ping_pong() -> None:
    text = _pad(
        "\n".join(
            [
                "「跑完了？」",
                "「跑完了。」",
                "「少了谁？」",
                "「点过了。」",
            ]
        )
    )
    assert max_short_quote_run(text) >= 4
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True


def test_staccato_narrative_chips() -> None:
    text = _pad("他进门。坐下。倒了水。喝一口。抬头。")
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_unit_run") or 0) >= 5


def test_staccato_skips_yudafu_full_spoken_lines() -> None:
    text = (
        "「你何以只住在家里，不出去找点事情做做？」\n"
        "「我原是这样的想，但是找来找去总找不着事情。」\n"
        "「你家在什么地方？何以不回家去？」\n"
        "经她这一问，我重新把半年来困苦的情形一层一层的想了出来。"
        "所以听她的问话以后，我只是呆呆的看她，半晌说不出话来。"
    )
    assert max_short_quote_run(text) == 0
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_skips_kongyiji_flat() -> None:
    text = (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。做工的人，傍午傍晚散了工，每每花四文铜钱，"
        "买一碗酒，——这是二十多年前的事，现在每碗要涨到十文，——靠柜外站着喝。"
    ) * 2
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_flags_three_short_duet() -> None:
    """三句对拍已是机械目录，不再放行。"""
    text = _pad("「来了？」\n「来了。」\n「坐。」\n他在门槛上磕掉鞋底的泥，把帽子挂到钉子上。")
    assert max_short_quote_run(text) == 3
    assert max_duet_quote_run(text) >= 3
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_duet_run") or 0) >= 3


def test_staccato_ledger_telegraph() -> None:
    """「进来拿。」「我会还。」「先记账。」「记多久？」 is the same mechanical beat."""
    body = "\n\n".join(["「进来拿。」", "「我会还。」", "「先记账。」", "「记多久？」"])
    assert max_short_quote_run(body) >= 4
    assert staccato_fields(body).get("staccato_uniform") is True
    assert staccato_fields(_pad(body)).get("staccato_uniform") is True


def test_staccato_ledger_same_line_and_tagged() -> None:
    text = "掌柜说：「进来拿。」他说：「我会还。」「先记账。」「记多久？」"
    assert max_short_quote_run(text) >= 4
    assert staccato_fields(text).get("staccato_uniform") is True


def test_staccato_receipt_beats_hinge() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={
            "status": "drafted",
            "staccato_uniform": True,
            "hinge_dense": True,
        },
    )
    assert should_inject_verify_receipt(state, reserve_steps=10) is True
    assert verify_receipt_kind(state) == "staccato"
    text = build_verify_receipt_text(state)
    assert "机械一问一答" in text
    assert "进来拿" in text
    assert "多轮空问" in text
    assert "一两句" in text
    assert "我知道" in text
    assert "你有名字吗" in text
    assert "是A，不是B" in text or "不是B" in text
    assert "因为" in text
    assert "propose_patch" in text
    assert "draft_section 或" not in text
    assert "neighbor" in text
    assert "旁白" in text
    assert "有人把话说满" not in text
    assert "展开日子时把场面写完" not in text
    assert "一次写满整窗" not in text
    kind = mark_verify_receipt_injected(state)
    assert kind == "staccato"
    assert state.staccato_receipt_sent is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is False


def test_staccato_flags_paper_handoff_rounds() -> None:
    """同一拍拆成收存/看清了/给我/会死，不是「太短」。"""
    body = _pad(
        "\n".join(
            [
                "「此物由巡夜司收存。」",
                "「你看清上面写的什么了吗？」",
                "「看清了。」",
                "「那就把它给我。」",
                "「你拿着它，明日就会死。」",
            ]
        )
    )
    assert staccato_fields(body).get("staccato_uniform") is True
    from app.writing.signals.repair import repair_hint

    hint = repair_hint("staccato_uniform", "web_serial")
    assert "一两句" in hint
    assert "旁白" in hint


def test_staccato_cleared_by_clean_draft() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "staccato_uniform": True},
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "visible_chars": 200},
    )
    assert state.staccato_pending is False
    assert should_inject_verify_receipt(state) is False


def test_staccato_cleared_by_clean_patch() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "staccato_uniform": True},
    )
    assert state.staccato_pending is True
    note_tool_result_for_verify(
        state,
        tool_name="propose_patch",
        result={
            "status": "applied",
            "writing_signals": {
                "penalties": [],
                "net_signal": 1.0,
                "composite": 0.83,
            },
        },
    )
    assert state.staccato_pending is False
    assert should_inject_verify_receipt(state) is False


def test_pending_patch_does_not_clear_staccato() -> None:
    uid = uuid4()
    state = TurnState(
        turn_id=uid,
        session_id=uid,
        run_id=uid,
        trace_id=uid,
        scenario_id="writing",
        max_steps=40,
        step_count=2,
    )
    note_tool_result_for_verify(
        state,
        tool_name="draft_section",
        result={"status": "drafted", "staccato_uniform": True},
    )
    note_tool_result_for_verify(
        state,
        tool_name="propose_patch",
        result={"status": "pending", "path": "drafts/manuscript.md"},
    )
    assert state.staccato_pending is True
    assert should_inject_verify_receipt(state, reserve_steps=10) is True


def test_staccato_phatic_acks_with_narrative_between() -> None:
    """「我知道」「嗯」「不懂」「懂」 look direct but add no move."""
    text = _pad(
        "「我知道」\n师傅点了下头。\n「嗯」\n他没再问。\n「不懂」\n「懂」\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_phatic") or 0) >= 3


def test_staccato_skips_lai_le_echo() -> None:
    """「来了？」「来了。」 is an answer, not an empty ack."""
    text = _pad("「来了？」\n「来了。」\n他在门槛上磕掉鞋底的泥。")
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_skips_brick_move() -> None:
    """「砖歪了」「歪了就摆正」 adds a move."""
    text = _pad(
        "「砖歪了。」\n「歪了就摆正。」\n他蹲下去，把砖角敲回槽里，灰从指缝掉下来。\n"
    )
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_scattered_phatic_does_not_fire() -> None:
    """Empty acks with a real line between them are not a run."""
    text = _pad(
        "「嗯。」\n他蹲下去把砖角敲回槽里，灰从指缝掉下来。\n"
        "「这块砖要重砌。」\n门外有人推车过去，轮子碾过积水。\n"
        "「我知道。」\n他把帽子挂到钉子上。\n"
        "「把门关上。」\n「懂。」\n"
    )
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_logic_glue_quotes() -> None:
    text = _pad(
        "「所以这块砖不能再用。」\n他看了看槽。\n"
        "「因此你今晚把名册补上。」\n门外还在下雨。\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_logic") or 0) >= 2


def test_staccato_defer_tells() -> None:
    text = _pad(
        "他没有立即回话，先看了看槽。她没有立即出门，先把帽子挂上。"
        "掌柜没有立即算账，先把粉板取下来。\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_defer") or 0) >= 3


def test_staccato_echo_know_repeat() -> None:
    text = _pad(
        "「这块砖为什么歪」\n「我知道这块砖为什么歪」\n"
        "「名册上有谁」\n「我知道名册上有谁」\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_echo") or 0) >= 2


@pytest.mark.asyncio
async def test_draft_section_sets_staccato_uniform(workspace) -> None:
    from app.tools.core import tools as core

    body = _pad(
        "\n".join(
            [
                "「跑完了？」",
                "「跑完了。」",
                "「少了谁？」",
                "「点过了。」",
            ]
        )
    )
    result = await core.draft_section("ch1", body, turn_id=uuid4())
    assert result.get("staccato_uniform") is True


def test_staccato_split_he_said_one_utterance() -> None:
    text = "「你家。」他说，「你袖口那块布，就是锁。」"
    fields = staccato_fields(text)
    assert count_split_speech(text) >= 1
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_split") or 0) >= 1


def test_staccato_contrast_punch_after_short_qa() -> None:
    text = "「不在了。」\n「你怎么知道？」\n「他来找的是包，不是我。」"
    fields = staccato_fields(text)
    assert count_contrast_punches(text) >= 1
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_contrast") or 0) >= 1


def test_staccato_skips_luxun_comma_attribution() -> None:
    text = (
        "「你该记得罢，」母亲便向着我说，「这是斜对门的杨二嫂，……开豆腐店的。」"
    )
    assert count_split_speech(text) == 0
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_equate_punch_is_metaphor_upgrade() -> None:
    text = "「你袖口那块布，就是锁。」"
    assert count_equate_punches(text) >= 1
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_equate") or 0) >= 1


def test_staccato_skips_aq_whatever_is_whatever() -> None:
    text = "阿Q更加高兴的走而且喊道：「好，……我要什么就是什么，我欢喜谁就是谁。」"
    assert count_equate_punches(text) == 0
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_allows_because_in_dialogue() -> None:
    text = _pad(
        "「他来找包，因为只问包在哪。」\n"
        "她把灯芯拨正，油烟贴在碗沿上。\n"
    )
    assert "staccato_uniform" not in staccato_fields(text)


def test_staccato_antithesis_clock_house() -> None:
    """「钟不知道，屋子知道。」 is a closing 对仗, not a watch-shop answer."""
    text = _pad("「电池还能撑一阵。」他擦了擦玻璃。\n「钟不知道，屋子知道。」他说。\n")
    assert count_antithesis_punches(text) >= 1
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_antithesis") or 0) >= 1
    span = find_staccato_span(text)
    assert "钟不知道" in span
    assert "屋子知道" in span
    assert not span.startswith("说。")


def test_find_staccato_span_prefers_antithesis_over_split() -> None:
    text = _pad(
        "「看不懂。」他说，「但是坏东西总有个坏法。」\n"
        "「钟不知道，屋子知道。」他说。\n"
    )
    span = find_staccato_span(text)
    assert "钟不知道" in span
    assert "看不懂" not in span


def test_staccato_skips_both_sides_unknown() -> None:
    text = _pad("「我不知道，他不知道。」桌上的油还没干。")
    assert count_antithesis_punches(text) == 0
    assert "staccato_uniform" not in staccato_fields(text)


def test_find_staccato_span_does_not_start_at_shuo_period() -> None:
    text = (
        "「绳子给我。」他说。\n\n"
        "一个工人拉住他，指压住地图上的红线。\n"
        "「进来拿。」\n「我会还。」\n「先记账。」\n「记多久？」\n"
    )
    span = find_staccato_span(text)
    assert span
    assert not span.startswith("说。")
    assert not span.startswith("指压住")
    assert span.lstrip().startswith("「") or "说：" in span[:6]
    assert "进来拿" in span
    assert "记多久" in span


_AI_BANTER = (
    "「那时候刀太钝。」\n"
    "「刀钝你也哭。」\n\n"
    "她低头挑起一筷子面，吹了吹，没有马上吃。过了一会儿，她说："
    "「你小时候也这样，话说得好听，事情未必做得到。」\n"
    "「现在呢？」\n"
    "「现在还要看。」\n"
    "「八点半。」\n"
    "「那早点睡。」\n"
    "「你到家给我发个消息。」\n"
    "「知道。」\n"
)


def test_staccato_flags_echo_twist_and_logistics_catalog() -> None:
    fields = staccato_fields(_AI_BANTER)
    assert fields.get("staccato_uniform") is True
    assert count_echo_twists(_AI_BANTER) >= 2
    assert count_thesis_mouth(_AI_BANTER) >= 1
    assert max_logistics_quote_run(_AI_BANTER) >= 3
    span = find_staccato_span(_AI_BANTER)
    assert "刀太钝" in span
    assert "刀钝你也哭" in span
    assert "八点半" not in span


def test_staccato_logistics_catalog_alone() -> None:
    text = _pad(
        "「八点半。」\n「那早点睡。」\n「你到家给我发个消息。」\n「知道。」\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_logistics") or 0) >= 3
    span = find_staccato_span(text)
    assert "八点半" in span
    assert "发个消息" in span


def test_staccato_echo_twist_from_narrative_setup() -> None:
    text = _pad(
        "她把筷子在碗沿上磕了磕，说那时候刀太钝，割绳都费劲。\n"
        "「刀钝你也照样出过活。」他没有接这句话。\n"
    )
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_echo_twist") or 0) >= 1
    span = find_staccato_span(text)
    assert "刀钝你也照样" in span


def test_staccato_span_expands_short_quote_cluster() -> None:
    text = _pad(
        "工人问：「谁签字？」\n老孙说：「我。」\n"
        "「你负责？」\n「负责。」\n"
    )
    span = find_staccato_span(text)
    assert "谁签字" in span
    assert "「我。」" in span or "我说" in span or "我。" in span
    assert "你负责" in span
    assert "负责。" in span


def test_gold_dialogue_exemplars_skip_echo_twist() -> None:
    from app.writing.signals.bank import load_platform_exemplars

    bank = load_platform_exemplars()
    for frag in ("dialogue_dyad", "mixed"):
        for sample in bank[frag]:
            fields = staccato_fields(sample.text)
            assert "staccato_uniform" not in fields, sample.slug


def test_theme_capsule_and_interview_ladder_flag_ai_voice() -> None:
    old_account = _pad(
        "秋兰看着她把账簿放回柜台，才说：「爹留下的那本，边角已经碎了。」\n"
        "「那是旧账，旧账碎了也只管旧账。」\n"
    )
    didactic = _pad(
        "沈太太放下一盏灯，低声说：「别看人家的东西。」\n"
        "「我没有看。」\n"
        "「眼睛看见了，心里也会记住。记住了就容易惹事。」\n"
    )
    interview = _pad(
        "「你认得那个人？」秋兰问。\n"
        "「不认得。」\n"
        "「那他为什么问我？」\n\n"
        "沈太太抬头看她。门外的风把河腥味送进来，吹动墙上的价目牌。"
        "煤油一角八分，灯芯三分，修铜嘴另算。那张纸边缘卷了起来，"
        "露出后面一行旧字，是沈老掌柜在世时留下的：欠陆家灯油，七角四分。\n\n"
        "沈太太把信塞进围裙口袋。「今天关门早些。」\n"
        "「为什么？」\n"
        "「河上要起雾。」\n"
    )
    debt = _pad(
        "秋兰的手按住那枚铜元，没有立刻拿走。「放在那里做什么？」\n"
        "沈太太低头看着她，过了片刻才说：「你爹欠下的账，不能让别人替他收。」\n"
    )
    ledger = _pad(
        "「不去。」\n"
        "「如果他们要的是账簿呢？」\n"
        "「家里没有账簿。」\n"
        "「柜台后面那本呢？」\n"
        "沈太太看着她，过了很久，才把手松开。「那本只记煤油和灯芯。」\n"
    )
    for sample in (old_account, didactic, interview, debt, ledger):
        fields = staccato_fields(sample)
        assert fields.get("staccato_uniform") is True, sample[:40]
    assert count_thesis_mouth(old_account) >= 1
    assert count_thesis_mouth(didactic) >= 1
    assert count_thesis_mouth(debt) >= 1
    assert count_thesis_mouth(ledger) >= 1
    assert max_interview_ladder(interview) >= 4
    assert max_interview_ladder(ledger) >= 4
    span = find_staccato_span(old_account)
    assert "旧账" in span
    span2 = find_staccato_span(didactic)
    assert "看见了" in span2 or "惹事" in span2
    span3 = find_staccato_span(interview)
    assert "认得" in span3
    assert "起雾" in span3 or "为什么" in span3


def test_duet_ping_pong_flags_and_locates() -> None:
    open_letter = _pad(
        "「你拆不拆？」老范问。\n"
        "「我的信，为什么拆？」\n"
        "「我看你脸色，像信里装了欠条。」\n"
    )
    street = _pad(
        "他看了一眼门外。卖糖水的白布棚还没有摆出来，桥那边只有几个挑担的人。"
        "「文庙后街。」\n"
        "「你住在那里。」\n"
        "「昨晚起，不住了。」\n"
    )
    assert max_duet_quote_run(street) >= 3
    assert staccato_fields(street).get("staccato_uniform") is True
    assert staccato_fields(open_letter).get("staccato_uniform") is True
    span = find_staccato_span(street)
    assert "文庙后街" in span
    assert "不住了" in span
    span2 = find_staccato_span(open_letter)
    assert "拆不拆" in span2 or "为什么拆" in span2


def test_find_staccato_span_skips_avoided_island() -> None:
    sep = "柜台上温着酒，粉板上记着十九个钱。\n\n" * 6
    text = _pad(
        "「眼睛看见了，心里也会记住。记住了就容易惹事。」\n\n"
        + sep
        + "「那是旧账，旧账碎了也只管旧账。」\n"
    )
    first = find_staccato_span(text)
    assert first
    second = find_staccato_span(text, avoid_old=first)
    assert second
    assert second != first
    assert ("旧账" in first) != ("旧账" in second)


def test_web_serial_staccato_same_as_literary() -> None:
    text = _pad("雨大。\n风紧。\n路滑。\n人稀。\n钟响。\n")
    assert staccato_fields(text).get("staccato_uniform") is True
    assert staccato_fields(text, work_mode="web_serial").get("staccato_uniform") is True


def test_web_serial_staccato_blocks_append() -> None:
    from app.writing.signals.repair import append_block_l0_keys, process_l0_hits

    penalties = [{"key": "staccato_uniform", "hit": True, "delta": -0.06}]
    assert process_l0_hits(penalties, work_mode="literary") == ["staccato_uniform"]
    assert process_l0_hits(penalties, work_mode="web_serial") == ["staccato_uniform"]
    assert "staccato_uniform" in append_block_l0_keys("literary")
    assert "staccato_uniform" in append_block_l0_keys("web_serial")


def test_find_staccato_span_prefers_densest_short_run() -> None:
    """先出现的三句对拍不应抢走后段四句碎问。"""
    text = _pad(
        "「把东西放进门里，门就会停！」\n"
        "「哪扇门？」\n"
        "「有门牌的那扇！」\n\n"
        "「明天中午十二点以前，打这个电话。别报警，别找平台。」\n"
        "「那你呢？」\n"
        "「我得回去关门。」\n"
        "「门外那东西还在。」\n"
        "「所以才要快。」\n"
    )
    span = find_staccato_span(text)
    assert "那你呢" in span
    assert "所以才要快" in span
    assert "哪扇门" not in span


def test_identity_reask_after_waybill_name() -> None:
    text = _pad(
        "收货人：林照。\n"
        "「你叫林照？」\n"
        "女孩没回答，只拼命往前跑。\n"
        + ("墙上的日期开始同时变化。" * 12)
        + "\n「林照。」\n"
        "女孩停住。\n"
        "「你有名字吗？」\n"
        "她回头看了他一眼，像是没想到他会问这个。\n"
        "「有。」\n"
        "「叫什么？」\n"
        "「林照。」\n"
    )
    assert count_identity_reasks(text) >= 1
    fields = staccato_fields(text)
    assert fields.get("staccato_uniform") is True
    assert int(fields.get("staccato_identity") or 0) >= 1
    span = find_staccato_span(text)
    assert "你有名字吗" in span
    assert "叫什么" in span


def test_identity_reask_skips_first_introduction() -> None:
    text = _pad(
        "「你有名字吗？」\n"
        "「有。」\n"
        "「叫什么？」\n"
        "「林照。」\n"
    )
    assert count_identity_reasks(text) == 0
