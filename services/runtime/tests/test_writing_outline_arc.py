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


@pytest.mark.asyncio
async def test_update_outline_sets_arc_flags(workspace) -> None:
    from app.tools.core import tools as core

    result = await core.update_outline(_six_days(), turn_user_text="写长篇章纲")
    assert result.get("outline_no_spine") is True
    assert result.get("outline_no_peak") is True
    assert "长篇编排" in str(result.get("summary"))
