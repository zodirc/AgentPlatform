"""Long-outline spine / peak facts (not TOC-thin)."""

from __future__ import annotations

import pytest

from app.writing.outline_arc import (
    extract_outline_job,
    extract_outline_spine,
    outline_arc_fields,
)


def _six_days() -> str:
    day = "地方、活计、规矩和关系变化写开。" * 12
    return "".join(f"# 第{n}章\n{day}\n" for n in ("一", "二", "三", "四", "五", "六"))


def test_outline_arc_skips_short_and_toc() -> None:
    md = "".join(f"# 第{n}章\n日子。\n" for n in ("一", "二", "三"))
    assert outline_arc_fields(md, "写章纲") == {}
    long = _six_days()
    assert outline_arc_fields(long, "只要目录") == {}
    assert outline_arc_fields(long, "写个短篇") == {}


def test_outline_arc_flags_no_spine_no_peak() -> None:
    fields = outline_arc_fields(_six_days(), "写长篇章纲")
    assert fields.get("outline_no_spine") is True
    assert fields.get("outline_no_peak") is True
    assert "主线" in str(fields.get("summary_suffix"))
    assert "顶点" in str(fields.get("summary_suffix")) or "高潮" in str(
        fields.get("summary_suffix")
    )


def test_outline_arc_ok_when_spine_and_one_peak() -> None:
    day = "地方、活计、规矩和关系变化写开。" * 12
    md = (
        "主线：沈禾要保住铺子，挡着的是粮行的账。副线：弟弟跑腿，必须磕到这笔账上。\n"
        "高潮落在第六章摊牌。\n"
        + "".join(f"# 第{n}章\n{day}\n" for n in ("一", "二", "三", "四", "五"))
        + f"# 第六章\n{day}本卷顶点：粮行上门摊牌，铺子账到顶。\n"
    )
    assert outline_arc_fields(md, "写长篇") == {}


def test_outline_arc_peak_flood() -> None:
    day = "地方、活计、规矩和关系变化写开。" * 8
    md = (
        "主线：谁要保住铺子，挡着的是粮行。\n"
        + "".join(
            f"# 第{n}章\n{day}本章高潮摊牌决战。\n"
            for n in ("一", "二", "三", "四", "五", "六")
        )
    )
    fields = outline_arc_fields(md, "写长篇")
    assert fields.get("outline_peak_flood") is True
    assert fields.get("outline_no_peak") is None


def test_outline_arc_flags_opening_institution() -> None:
    md = (
        "主线：陆沉要一口安稳饭，挡着的是药园规矩。副线：同门必须磕到工分上。\n"
        "高潮落在第六章摊牌。\n"
        "1—5：陆沉在玄微宗后山药园当杂役，熟悉浇灌。\n"
        "### 第一章 灰渠里的水声\n"
        "写陆沉当下如何在后山药园过一天。第一章只写玄微宗药园的当下日子。\n"
    )
    fields = outline_arc_fields(md, "写长篇六百章")
    assert fields.get("outline_institution_first") is True
    assert "机构专名" in str(fields.get("summary_suffix"))


def test_outline_arc_ok_when_place_before_sect() -> None:
    day = "地方、活计、规矩和关系变化写开。" * 12
    md = (
        "主线：沈禾要保住铺子，挡着的是粮行的账。副线：弟弟跑腿，必须磕到这笔账上。\n"
        "高潮落在第六章摊牌。\n"
        "1—5：青石镇东口药田少水，陆沉被罚清渠；有人后口才提起玄微宗收粮。\n"
        "### 第一章 灰渠\n职务：铺垫，先写镇口药田和工钱。\n"
        + "".join(f"# 第{n}章\n{day}\n" for n in ("一", "二", "三", "四", "五"))
        + f"# 第六章\n{day}本卷顶点：粮行上门摊牌，铺子账到顶。\n"
    )
    assert outline_arc_fields(md, "写长篇") == {}


def test_opening_trilogy_fields_long_form() -> None:
    from app.writing.outline_arc import opening_trilogy_fields

    missing = opening_trilogy_fields("", "写长篇玄幻小说")
    assert missing.get("outline_opening_trilogy_missing") is True

    ok = (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n环境：霜降边城，渡口灯油规矩，谁交谁过。\n" + "细节。" * 30
        + "\n### ch2\n规则：灵灯是引路法器，无油不应亮；灯司掌登记。\n" + "细节。" * 30
        + "\n### ch3\n人物：裴照修灯，第一阶异常是旧灯无油自亮。\n" + "细节。" * 30
    )
    assert opening_trilogy_fields(ok, "写长篇") == {}

    suspense = (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n环境：现代小城，夜班公交末班，乘客按站刷卡。\n" + "细节。" * 30
        + "\n### ch2\n悬念：第二起失踪，对讲机里多出一段无人认领的报站。\n" + "细节。" * 30
        + "\n### ch3\n人物：杨间被卷入，第一阶麻烦是不得不上那班车。\n" + "细节。" * 30
    )
    assert opening_trilogy_fields(suspense, "写长篇") == {}

    no_duty_labels = (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n霜降那天渡口还开着，灯油按人收，过河的把铜钱拍在板上。\n"
        + "细节。" * 30
        + "\n### ch2\n对讲机里多出一段无人认领的报站，第二起失踪还没人认。\n"
        + "细节。" * 30
        + "\n### ch3\n杨间被叫去顶班，末班车上只剩他和那个报站声。\n"
        + "细节。" * 30
    )
    assert opening_trilogy_fields(no_duty_labels, "写长篇") == {}

    short_notes = (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n盐筛场收工，陆沉把工牌揣进怀里，今晚还要去领药。\n"
        "### ch2\n外门报到，名额是借来的，三年工契压在验砂桌上。\n"
        "### ch3\n废器房第一炉，账对不上，管事要人顶损耗。\n"
    )
    assert opening_trilogy_fields(short_notes, "写长篇") == {}

    stubs = (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n待写。\n"
        "### ch2\n待写。\n"
        "### ch3\n待写。\n"
    )
    assert opening_trilogy_fields(stubs, "写长篇").get(
        "outline_opening_trilogy_incomplete"
    ) is True

    ch1_only = (
        "## 这本书（长篇·眼前这一池）\n\n"
        "### ch1\n盐筛场收工，陆沉把工牌揣进怀里，今晚还要去领药。\n"
    )
    assert opening_trilogy_fields(ch1_only, "写长篇") == {}


def test_extract_spine_and_job() -> None:
    md = (
        "主线：沈禾要保住铺子，挡着的是粮行的账。\n\n"
        "# 第三章\n加压：账房来核秤，弟弟把粮单藏进袖子。\n"
        "# 第六章\n摊牌。\n"
    )
    assert "保住铺子" in extract_outline_spine(md)
    job = extract_outline_job(md, "ch3")
    assert "核秤" in job
    assert extract_outline_job(md, "ch2") == ""


def test_outline_templates_do_not_prime_same_book_under_new_coat() -> None:
    from app.writing.outline_arc import (
        OPENING_TRILOGY_OUTLINE_TEMPLATE,
        STYLE_CONTRACT_OUTLINE_TEMPLATE,
    )
    from app.controller.input_compiler import OUTLINE_EXPAND

    for blob in (
        STYLE_CONTRACT_OUTLINE_TEMPLATE,
        OPENING_TRILOGY_OUTLINE_TEMPLATE,
    ):
        assert "（谁要什么、谁挡着、顶点落在哪）" not in blob
        assert "读者追什么" not in blob
        assert "看见代价" not in blob
        assert "由谁承担" not in blob
        assert "另一本书" in blob
        assert "跟着谁" in blob
        assert "眼下要什么" in blob
        assert "直说" in blob or "两三句" in blob
        assert "200–400" not in blob
        assert "不是另起的寓意" not in blob
        assert "路数不是换皮" not in blob
        assert "**路数**" not in blob
        assert "路数" not in blob
        assert "**边界**" not in blob
        assert "世界契约" not in blob
        assert "主题倾向" not in blob
        assert "沈砚" not in blob
        assert "沈禾" not in blob
    assert "谁要什么、谁挡着" not in OUTLINE_EXPAND
    assert "眼前这一池" in OUTLINE_EXPAND


def test_outline_arc_ok_when_spine_follows_style_not_want_block() -> None:
    day = "地方、活计、规矩和关系变化写开。" * 12
    md = (
        "主线：井下唤的是谁，第一案要验得住。\n"
        "高潮落在第六章对质。\n"
        + "".join(f"# 第{n}章\n{day}\n" for n in ("一", "二", "三", "四", "五"))
        + f"# 第六章\n{day}本卷顶点：当堂对质，物证对得上。\n"
    )
    assert outline_arc_fields(md, "写长篇") == {}


@pytest.mark.asyncio
async def test_update_outline_sets_arc_flags(workspace) -> None:
    from app.tools.core import tools as core

    result = await core.update_outline(_six_days(), turn_user_text="写长篇章纲")
    assert result.get("outline_no_spine") is True
    assert result.get("outline_no_peak") is True
    assert "长篇编排" in str(result.get("summary"))


@pytest.mark.asyncio
async def test_update_outline_volume_syncs_deferred(workspace) -> None:
    from app.tools.core import tools as core
    from app.writing.story_state import load_story_state

    result = await core.update_outline(
        "主线：还在河东。\n",
        turn_user_text="写长篇",
        volume={
            "index": 2,
            "chapters": "ch6-ch10",
            "questions": ["她到底会不会再去码头"],
            "must_not_decide_yet": ["父亲是否知情"],
            "promises_due": ["第 3 章欠读者的：那封信里写了什么"],
            "where_it_stands": "还在河东；冬天还没到",
        },
    )
    text = (workspace / "outline.md").read_text(encoding="utf-8")
    assert "## 卷 2" in text
    assert "父亲是否知情" in text
    state = load_story_state(workspace_root=workspace)
    questions = [d.get("question") for d in (state.get("deferred") or [])]
    assert "父亲是否知情" in questions
    assert result.get("path") == "outline.md"


def test_outline_style_committed_person_slot_without_route() -> None:
    from app.writing.outline_arc import outline_style_committed

    person = (
        "## 风格契约\n\n"
        "**这本在写谁**：韩校尉在井口核帖，袖口还沾着泥。\n\n"
        "**这本在写什么**：井下那张帖要验得住，今夜必须对上账。\n\n"
        "**世界怎么运转**：衙门、税册、案卷织网；超凡要查得证。\n\n"
        "**文字与节奏**：市井气，一案一结，句子跟着脚步走。\n"
    )
    assert "凡人流" not in person
    assert outline_style_committed(person) is True

    legacy = (
        "## 风格契约\n\n**路数**：凡人流\n\n"
        "**世界怎么运转**：灵石、丹药、引荐都要换；散修与内门隔着工分。\n\n"
        "**文字与节奏**：惜命算计，打斗写消耗。\n\n"
        "**开篇质地**：生计压力进门派。\n\n"
        "**边界**：忌天才顿悟。\n"
    )
    assert outline_style_committed(legacy) is False

    thin = "## 风格契约\n\n还没写满。\n"
    assert outline_style_committed(thin) is False


def test_opening_sea_spill_flags_ending_in_pond() -> None:
    from app.writing.outline_arc import opening_sea_spill, outline_arc_fields

    md = (
        "## 这本书（长篇·眼前这一池）\n\n"
        "**跟着谁**：陆沉在盐筛场收工。\n"
        "**眼下要什么**：今晚把工牌换成药。\n"
        "**读者站在哪**：边镇盐场。\n"
        "**这一章干什么**：站住日子。终局宇宙里他飞升成神，全书结局是改命。\n"
    )
    assert "海" in opening_sea_spill(md)
    fields = outline_arc_fields(md, "写长篇")
    assert fields.get("outline_opening_sea") is True
