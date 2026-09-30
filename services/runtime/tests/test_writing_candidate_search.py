from __future__ import annotations

import json

import pytest

from app.writing import candidate_sample
from app.writing.candidate_search import (
    CARD_SELECTION_SCHEMA,
    DIRECTION_SET_SCHEMA,
    RENDER_SCHEMA,
    card_selection_messages,
    direction_set_messages,
    parse_card_selection,
    parse_direction_set,
    render_messages,
)


def _intent() -> dict[str, bool]:
    return {
        "no_human_pull": False,
        "genre_decorative": False,
        "noun_graft": False,
        "moral_pre_solved": False,
        "no_serial_engine": False,
    }


def test_search_contract_parsers_are_small_and_bounded() -> None:
    assert DIRECTION_SET_SCHEMA["required"] == ["ideas"]
    assert RENDER_SCHEMA["required"] == ["title", "pitch"]
    assert CARD_SELECTION_SCHEMA["required"] == ["first", "second"]
    assert parse_direction_set('{"ideas":["甲","乙","丙","丁"]}') == [
        "甲",
        "乙",
        "丙",
        "丁",
    ]
    assert parse_card_selection('{"first":2,"second":0}', 4) == [2, 0]
    assert parse_card_selection('{"first":-1,"second":1}', 4) == [1]
    assert parse_card_selection('{"first":true,"second":"bad"}', 4) == []


def test_search_contract_stays_at_book_identity_not_first_arc_outline() -> None:
    direction_blob = candidate_sample._content_text(
        direction_set_messages("写一部长篇都市修真小说")
    )
    render_messages_full = render_messages(
        "写一部长篇都市修真小说", "一个宽阔的作品方向"
    )
    render_blob = candidate_sample._content_text(render_messages_full)
    selection_blob = candidate_sample._content_text(
        card_selection_messages(
            "写一部长篇都市修真小说",
            [{"title": "长夜", "pitch": "一座城市与修行时代的漫长故事。"}],
        )
    )
    assert "作品身份搜索" in direction_blob
    assert "书城上会并列陈列的不同开书" in direction_blob
    assert "商业网文书页上的泛化简介" in render_blob
    assert "目标口吻与抽象层级" in render_blob
    assert any(msg.get("role") == "assistant" for msg in render_messages_full)
    assert sum(1 for msg in render_messages_full if msg.get("role") == "assistant") == 3
    assert "listing_affinity" in selection_blob
    assert "像书城上两本不同的书" in selection_blob
    assert RENDER_SCHEMA["properties"]["pitch"]["maxLength"] == 180


def test_listing_affinity_soft_ranks_blurbs_without_hard_reject() -> None:
    from app.writing.candidate_search import listing_affinity

    good = listing_affinity(
        "现代城市里，修行并未消失。普通人一旦入门，就将走进另一套缓慢展开的生活与天地。"
    )
    rhetorical = listing_affinity(
        "他必须决定，是把城市变成花圃，还是给别人留下活路。"
    )
    overplotted = listing_affinity(
        "他主动修习。第一次看见亡魂。第二次找到遗骨。第三次怀疑母亲。第四次写下笔记。"
    )
    assert good > rhetorical
    assert good > overplotted


def test_diversify_selected_cards_replaces_near_duplicate_pair() -> None:
    from app.writing.candidate_search import diversify_selected_cards

    cards = [
        {
            "title": "城市藏息",
            "pitch": "这座城市照常运转，写字楼与旧街区之间藏着修行秩序。普通人由此踏入，渐渐看见城市更深处。",
        },
        {
            "title": "共修时代",
            "pitch": "这座城市照常运转，日常与隐秘世界交叠。普通人由此踏入，渐渐看见城市更深处的辽阔。",
        },
        {
            "title": "余火纪年",
            "pitch": "倘若天地真是一片漫长的暗处，修真者也只会把自己燃成一点火。火再小，只要前赴后继，终会照见更大的世界。",
        },
    ]
    selected = diversify_selected_cards(cards, cards[:2])
    titles = {card["title"] for card in selected}
    assert "余火纪年" in titles
    assert len(selected) == 2


@pytest.mark.asyncio
async def test_render_keeps_rhetorical_card_for_soft_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(messages, **_kwargs):
        return candidate_sample.CompleteResult(
            text=json.dumps(
                {
                    "title": "还是之书",
                    "pitch": "他想保住屋顶花园，也想保住邻居的修行。他必须决定，是把城市变成自己的花圃，还是给别人留下活路。",
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(candidate_sample, "_run_complete", fake_run)
    card = await candidate_sample._render_direction(
        "写一部长篇都市修真小说",
        "都市中普通人开始修行",
        sample_id="t01",
        exclude_fingerprints=set(),
        exclude_titles=set(),
    )
    assert card is not None
    assert card["title"] == "还是之书"


def test_sample_surface_guards_remain_available_for_soft_signals() -> None:
    from app.writing.work_reconstruction import (
        obvious_sample_overplot,
        obvious_sample_rhetoric,
    )

    assert obvious_sample_rhetoric(
        "他必须决定，是把城市变成花圃，还是给别人留下活路。"
    )
    assert not obvious_sample_rhetoric(
        "现代城市里，修行并未消失。普通人一旦入门，就将走进另一套缓慢展开的生活与天地。"
    )
    assert obvious_sample_overplot(
        "他主动修习。第一次看见亡魂。第二次找到遗骨。第三次怀疑母亲。第四次写下笔记。"
    )
    assert not obvious_sample_overplot(
        "现代城市里，修行并未消失。普通人一旦入门，就将走进另一套缓慢展开的生活与天地。"
    )


@pytest.mark.asyncio
async def test_live_search_maps_four_renders_all_then_selects_finished_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ideas = [
        "方向甲：普通人偶然获得一门修行法，从第一次入定开始进入城市里的修行生活。",
        "方向乙：昔日修士回到现代社会，一边恢复修为，一边重新理解今天的人际关系。",
        "方向丙：年轻人主动寻找修行道路，逐步结识同道、突破境界并扩大活动范围。",
        "方向丁：已经入门的小修士在城市生活中尝试把能力用在自己真正想做的事上。",
    ]
    selector_blob = ""
    render_blobs: list[str] = []
    calls = {"direction": 0, "selection": 0, "render": 0, "gate": 0}
    routes: dict[str, list[object]] = {key: [] for key in calls}

    async def fake_run(messages, **kwargs):
        nonlocal selector_blob
        blob = candidate_sample._content_text(messages)
        if "铺开四个真正不同的作品方向" in blob:
            stage = "direction"
            calls["direction"] += 1
            payload = {"ideas": ideas}
        elif "你是作品候选的终审" in blob:
            stage = "selection"
            calls["selection"] += 1
            selector_blob = blob
            payload = {"first": 2, "second": 0}
        elif "把给定方向写成一张作品候选卡" in blob:
            stage = "render"
            calls["render"] += 1
            render_blobs.append(blob)
            index = next(index for index, idea in enumerate(ideas) if idea in blob)
            distinct = [
                "普通人第一次摸到修行门径，城市日常仍按原样运转，机缘却从另一套规矩里长出来。",
                "昔日修士归来，现代社会的人情与旧日道统并立，求道变成重新理解当下的关系。",
                "年轻人主动寻访同道，活动范围从街区扩到更远的山野与城际之间。",
                "已入门的小修士把能力用在自己真正想做的事上，修行与生活互相改写边界。",
            ]
            payload = {
                "title": f"方向书{index}",
                "pitch": distinct[index],
            }
        elif "你是作品前提标注员" in blob:
            stage = "gate"
            calls["gate"] += 1
            payload = {"intent": _intent()}
        else:
            raise AssertionError(blob)
        routes[stage].append(kwargs.get("model_route"))
        return candidate_sample.CompleteResult(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(candidate_sample, "_run_complete", fake_run)
    cards = await candidate_sample.sample_independent_pair("写一部长篇都市修真小说")

    assert [card["title"] for card in cards] == ["方向书2", "方向书0"]
    assert [card["sample_id"] for card in cards] == ["c01", "c02"]
    assert calls == {"direction": 1, "selection": 1, "render": 4, "gate": 2}
    assert all(
        route == ("writing", "book_candidates")
        for stage in ("direction", "selection", "render")
        for route in routes[stage]
    )
    assert routes["gate"] == [None, None]
    assert all(f"方向书{index}" in selector_blob for index in range(4))
    assert len(render_blobs) == 4
    assert all(sum(idea in blob for idea in ideas) == 1 for blob in render_blobs)
    assert all("premise" not in card["raw"] for card in cards)


@pytest.mark.asyncio
async def test_search_runs_fresh_second_pass_when_first_cards_fail_quality_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"direction": 0, "selection": 0, "render": 0}
    first_ideas = ["首轮甲", "首轮乙", "首轮丙", "首轮丁"]
    second_ideas = ["新轮甲", "新轮乙", "新轮丙", "新轮丁"]

    async def fake_run(messages, **_kwargs):
        blob = candidate_sample._content_text(messages)
        if "铺开四个真正不同的作品方向" in blob:
            calls["direction"] += 1
            payload = {
                "ideas": second_ideas if "第二次独立搜索" in blob else first_ideas
            }
        elif "你是作品候选的终审" in blob:
            calls["selection"] += 1
            payload = (
                {"first": 0, "second": 1}
                if "新轮甲篇" in blob
                else {"first": -1, "second": -1}
            )
        elif "把给定方向写成一张作品候选卡" in blob:
            calls["render"] += 1
            idea = next(
                idea for idea in [*first_ideas, *second_ideas] if idea in blob
            )
            pitches = {
                "首轮甲": "底层街区里，修行仍是私下口耳相传的旧事。",
                "首轮乙": "公开考核把灵力写进升学与就业，城市按境界分层。",
                "首轮丙": "城与荒野的边界一夜迁徙，归来者要重新辨认家园。",
                "首轮丁": "旧宗门改挂现代牌匾，编制里藏着另一套天理。",
                "新轮甲": "表里两界用倒计时相连，被选中的人在街市与异境往返。",
                "新轮乙": "编号特区各自为政，九区少年只能从边界之内长出来。",
                "新轮丙": "修真文明以火种自喻，在远超都市的尺度上前赴后继。",
                "新轮丁": "双城并行，一边是人间编制，一边是山海异境。",
            }
            payload = {
                "title": f"{idea}篇",
                "pitch": pitches[idea],
            }
        elif "你是作品前提标注员" in blob:
            payload = {"intent": _intent()}
        else:
            raise AssertionError(blob)
        return candidate_sample.CompleteResult(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(candidate_sample, "_run_complete", fake_run)
    cards = await candidate_sample.sample_independent_pair("写一部长篇都市修真小说")

    assert [card["title"] for card in cards] == ["新轮甲篇", "新轮乙篇"]
    assert calls == {"direction": 2, "selection": 2, "render": 8}


@pytest.mark.asyncio
async def test_search_selects_only_from_cards_that_rendered_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ideas = ["方向甲", "方向乙", "方向丙", "方向丁"]
    selector_blob = ""

    async def fake_run(messages, **_kwargs):
        nonlocal selector_blob
        blob = candidate_sample._content_text(messages)
        if "铺开四个真正不同的作品方向" in blob:
            payload: object = {"ideas": ideas}
        elif "你是作品候选的终审" in blob:
            selector_blob = blob
            payload = {"first": 0, "second": 1}
        elif "把给定方向写成一张作品候选卡" in blob:
            if "方向甲" in blob or "方向乙" in blob:
                return candidate_sample.CompleteResult(text="not-json")
            idea = "方向丙" if "方向丙" in blob else "方向丁"
            payload = {
                "title": f"{idea}书",
                "pitch": f"{idea}形成的完整候选简介，并有行动后果。",
            }
        elif "你是作品前提标注员" in blob:
            payload = {"intent": _intent()}
        else:
            raise AssertionError(blob)
        return candidate_sample.CompleteResult(text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(candidate_sample, "_run_complete", fake_run)
    cards = await candidate_sample.sample_independent_pair("写一部长篇都市修真小说")

    assert [card["title"] for card in cards] == ["方向丙书", "方向丁书"]
    assert "方向甲" not in selector_blob
    assert "方向乙" not in selector_blob
