from __future__ import annotations

import asyncio
import json
import logging

import pytest

from app.writing.candidate_sample import (
    _FORM_MAX_OUTPUT_TOKENS,
    _FORM_THINK_CHAR_BUDGET,
    _SAMPLE_POOL,
    _content_text,
    _genre_label,
    _topic_of,
    consume_complete,
    form_generation,
    form_messages,
    sample_independent_pair,
    sample_one_candidate,
)
from app.writing.work_reconstruction import (
    build_candidate_context,
    parse_card,
    parse_selector_ids,
    parse_work,
    render_messages,
    selector_messages,
)


_GOOD_A = (
    "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
    "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
    "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
)
_TITLES = ["余烬", "潮汐"]
_FLAVOR = "日常已经把未完成当成常态，这本书靠这块现实站住。"


def _work(tag: str) -> str:
    return (
        f"{tag} 修仙早已成为旧日常识。活两百年并不稀奇。"
        "某种闭合从未真正出现。旧教材封面还印着已经不用的功法名。"
        "人们早就这样过日子，也不觉得需要另外解释。城里的人把这些事当成天气。"
    )


def _card(title: str) -> str:
    return json.dumps(
        {"title": title, "这本书": _FLAVOR, "opening": _GOOD_A},
        ensure_ascii=False,
    )


def _stage(text: str) -> str:
    if "已经冻结的候选概貌" in text:
        return "render"
    if "判尺只用来辨认哪个更像" in text:
        return "select"
    return "form"


def _banned_theory(blob: str) -> None:
    assert "work_intent" not in blob
    assert "reading_pull" not in blob
    assert "请设计" not in blob
    assert "请构思" not in blob
    assert "让它站住" not in blob
    assert "历史纵深" not in blob
    assert "长期连载潜力" not in blob
    assert "previous_attempt_discarded" not in blob
    assert "### TARGET SHELF" not in blob
    assert "plot_progress" not in blob
    assert "focus=ch1" not in blob
    assert "outline_phase" not in blob
    assert "story_state" not in blob
    assert "draft_section" not in blob
    assert "改变前面事实的意义" not in blob
    assert "work_core" not in blob
    assert "work_seed" not in blob
    assert "reality_residue" not in blob
    assert "second-order" not in blob
    assert "第二阶" not in blob
    assert "observe_from" not in blob
    assert "start_kind" not in blob
    assert "price_axis" not in blob
    assert "长时段变化" not in blob
    assert "已常态化现实" not in blob
    assert "生活沉积" not in blob
    assert "作品现实" not in blob


def test_genre_label_is_boundary_not_task() -> None:
    assert _genre_label("写一篇长篇都市修真小说") == "都市修真"
    assert _topic_of("写一篇长篇都市修真小说") == "长篇都市修真"


def test_form_is_a_loose_novel_sketch() -> None:
    ctx = build_candidate_context("写一篇长篇都市修真小说")
    assert ctx == {
        "genre": "都市修真",
        "fresh_work": True,
    }
    blob = _content_text(form_messages("写一篇长篇都市修真小说"))
    assert "genre = 都市修真" in blob
    assert "fresh_work = true" in blob
    assert "题材：都市修真" in blob
    assert "大概是什么样子" in blob
    assert "不要找最优" in blob
    assert "不用寻找最优方案" in blob
    assert "150～250字" in blob
    assert "架空世界" in blob
    assert "不使用现实世界的具体地名和事件" in blob
    assert "scope =" not in blob
    assert "mode =" not in blob
    assert "You are a writing assistant" not in blob
    assert "先写正在发生的事" not in blob
    assert "一本长篇小说本身" not in blob
    assert "已经成立的若干事实" not in blob
    assert "《人间未醒》" not in blob
    assert "飞升从来没有出现过" not in blob
    assert "title" not in blob.lower()
    assert "pitch" not in blob.lower()
    _banned_theory(blob)
    assert "[writing_context]" not in blob
    msgs = form_messages("写一篇长篇都市修真小说")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"


def test_selector_uses_gold_as_work_ruler() -> None:
    blob = _content_text(selector_messages([("c01", "修仙早已成为旧日常识。")]))
    assert "《人间未醒》" in blob
    assert "飞升从来没有出现过" in blob
    assert "已经成立的小说" in blob
    assert "是否有整体性" in blob
    assert "不要打分" in blob
    assert "c01" in blob
    assert "genre = 都市修真" not in blob
    _banned_theory(blob)


def test_renderer_packages_frozen_sketch_only() -> None:
    blob = _content_text(render_messages("修行已经改过几代，旧名还挂在嘴里。"))
    assert "已经冻结的候选概貌" in blob
    assert "修行已经改过几代，旧名还挂在嘴里。" in blob
    assert "这本书" in blob
    assert "架空世界" in blob
    assert "《人间未醒》" not in blob
    _banned_theory(blob)


def test_parse_work_and_card() -> None:
    text = _work("ONE")
    assert parse_work(text) == text
    assert parse_work("太短了") is None
    card = parse_card(_card("余烬"))
    assert card is not None
    assert card["title"] == "余烬"
    assert card["flavor"] == _FLAVOR
    assert card["opening"].startswith("灾变之后")
    assert parse_selector_ids('{"selected": ["c01", "c02"]}', ["c01", "c02"]) == [
        "c01",
        "c02",
    ]


def test_form_budget_is_medium_not_30k() -> None:
    form = form_generation()
    assert form.max_output_tokens == _FORM_MAX_OUTPUT_TOKENS
    assert _FORM_THINK_CHAR_BUDGET <= 8000
    assert form.tool_choice == "none"
    assert form.thinking_enabled is False
    assert form.reasoning_effort == "none"
    assert _SAMPLE_POOL == 2


@pytest.mark.asyncio
async def test_two_independent_sketches_then_select_then_render() -> None:
    seen: list[str] = []
    form_i = 0

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        seen.append(text)
        stage = _stage(text)
        if stage == "form":
            assert "《人间未醒》" not in text
            assert "previous_attempt_discarded" not in text
            assert "start_kind" not in text
            idx = form_i
            form_i += 1
            return _work(f"SNAP{idx}")
        if stage == "select":
            assert "《人间未醒》" in text
            assert "SNAP0" in text
            assert "SNAP1" in text
            return '{"selected": ["c01", "c02"]}'
        for i in range(_SAMPLE_POOL):
            if f"SNAP{i}" in text:
                return _card(_TITLES[i])
        raise AssertionError("render saw an unknown work")

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        gate=True,
        held=[{"title": "渡劫要报备", "opening": "旧卡"}],
    )
    assert [it["title"] for it in pair] == ["余烬", "潮汐"]
    assert pair[0]["flavor"] == _FLAVOR
    assert pair[0]["work"].startswith("SNAP0")
    assert pair[1]["work"].startswith("SNAP1")
    assert form_i == 2
    stages = [_stage(s) for s in seen]
    assert stages.count("form") == 2
    assert stages.count("select") == 1
    assert stages.count("render") == 2
    form_blobs = [s for s in seen if _stage(s) == "form"]
    assert len(set(form_blobs)) == 1
    assert not any("渡劫要报备" in s for s in seen)


@pytest.mark.asyncio
async def test_short_form_does_not_enter_pool() -> None:
    form_i = 0

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        stage = _stage(text)
        if stage == "form":
            idx = form_i
            form_i += 1
            if idx == 0:
                return "短。"
            return _work(f"SNAP{idx}")
        if stage == "select":
            return '{"selected": ["c01", "c02"]}'
        return _card("余烬")

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        need=2,
    )
    assert len(pair) == 2
    assert form_i == 3
    assert all(it["title"] == "余烬" for it in pair)


@pytest.mark.asyncio
async def test_pair_thinking_stays_on_one_sample_at_a_time(monkeypatch) -> None:
    from app.writing import candidate_sample as cs

    deltas: list[str] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int = 0) -> None:
        if event_type == "turn.thinking.delta":
            deltas.append(str(payload.get("delta") or ""))

    monkeypatch.setattr(
        "app.controller.runtime_context.get_event_writer",
        lambda: write_event,
    )

    form_i = 0

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        stage = _stage(text)
        await cs._emit_thinking_delta(f"<{stage}>")
        await asyncio.sleep(0.01)
        if stage == "form":
            idx = form_i
            form_i += 1
            return _work(f"SNAP{idx}")
        if stage == "select":
            return '{"selected": ["c01", "c02"]}'
        return _card("余烬")

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        need=2,
    )
    assert len(pair) == 2
    assert deltas.count("\n—— 独立采样 ——\n") == 2
    stages = [d for d in deltas if d.startswith("<")]
    assert stages == ["<form>", "<form>", "<select>", "<render>", "<render>"]


@pytest.mark.asyncio
async def test_independent_sample_does_not_resurrect_held_cards(
    workspace, monkeypatch
) -> None:
    from uuid import uuid4

    from app.settings import settings
    from app.tools.core.writing_tools import propose_book_candidates
    from app.writing.opening_ponds import (
        clear_pond_rejects,
        remember_held_pond_items,
        save_opening_ponds,
    )

    monkeypatch.setattr(settings, "ponds_excerpt_gate", True)
    clear_pond_rejects()
    turn_id = uuid4()
    save_opening_ponds(
        [
            {"title": "渡劫要报备", "opening": "修行要报备。"},
            {"title": "城隍夜巡", "opening": "路灯连着护城阵。"},
        ]
    )
    remember_held_pond_items(
        turn_id,
        [
            {"title": "渡劫要报备", "opening": "修行要报备。"},
            {"title": "城隍夜巡", "opening": "路灯连着护城阵。"},
        ],
    )
    form_i = 0

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        assert "渡劫要报备" not in text
        assert "城隍夜巡" not in text
        assert "previous_attempt_discarded" not in text
        stage = _stage(text)
        if stage == "form":
            idx = form_i
            form_i += 1
            return _work(f"NEW{idx}")
        if stage == "select":
            return '{"selected": ["c01", "c02"]}'
        return _card("余烬")

    result = await propose_book_candidates(
        [],
        turn_id=turn_id,
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "ok"
    titles = [it["title"] for it in result["items"]]
    assert titles == ["余烬", "余烬"]
    assert "渡劫要报备" not in titles
    assert "城隍夜巡" not in titles
    assert result["items"][0]["work"].startswith("NEW0")
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_handler_hard_excludes_previous_titles(workspace, monkeypatch) -> None:
    from uuid import uuid4

    from app.settings import settings
    from app.tools.core.writing_tools import propose_book_candidates
    from app.writing.opening_ponds import clear_pond_rejects, save_opening_ponds

    monkeypatch.setattr(settings, "ponds_excerpt_gate", True)
    clear_pond_rejects()
    turn_id = uuid4()
    save_opening_ponds(
        [
            {"title": "渡劫要报备", "opening": "修行要报备。"},
            {"title": "城隍夜巡", "opening": "路灯连着护城阵。"},
        ]
    )

    async def complete(messages):
        text = _content_text(messages)
        stage = _stage(text)
        if stage == "form":
            return _work("OLD")
        if stage == "select":
            return '{"selected": ["c01", "c02"]}'
        if "OLD" in text:
            return _card("渡劫要报备")
        return _card("余烬")

    result = await propose_book_candidates(
        [],
        turn_id=turn_id,
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "error"
    assert result.get("fresh_retry") is True
    assert "渡劫要报备" not in json.dumps(result, ensure_ascii=False)
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_sample_one_forms_sketch_only(caplog) -> None:
    stages: list[str] = []

    async def complete(messages):
        text = _content_text(messages)
        stages.append(_stage(text))
        assert "《人间未醒》" not in text
        return _work("ONE")

    with caplog.at_level(logging.INFO, logger="app.writing.candidate_sample"):
        item = await sample_one_candidate("写一篇长篇都市修真小说", complete=complete)
    assert item is not None
    assert item["work"].startswith("ONE")
    assert stages == ["form"]
    traces = [
        json.loads(rec.getMessage().removeprefix("candidate_trace "))
        for rec in caplog.records
        if rec.getMessage().startswith("candidate_trace ")
    ]
    assert traces[-1]["work"].startswith("ONE")
    assert traces[-1]["selected"] is False
    assert traces[-1]["title"] == ""
    assert traces[-1]["opening"] == ""


@pytest.mark.asyncio
async def test_collect_complete_text_forwards_reasoning(monkeypatch) -> None:
    from app.model.gateway import ModelResponse, StreamActivity
    from app.writing.candidate_sample import collect_complete_text

    events: list[tuple[str, dict]] = []

    async def write_event(*, event_type: str, payload: dict, step_index: int = 0) -> None:
        events.append((event_type, payload))

    monkeypatch.setattr(
        "app.controller.runtime_context.get_event_writer",
        lambda: write_event,
    )

    async def stream():
        yield StreamActivity(kind="sse", text="")
        yield StreamActivity(kind="reasoning", text="先决定这本书是什么")
        yield "formed seed"
        yield ModelResponse(text="formed seed")

    text = await collect_complete_text(stream())
    assert text == "formed seed"
    assert events == [
        ("turn.thinking.delta", {"delta": "先决定这本书是什么", "step_index": 0})
    ]


@pytest.mark.asyncio
async def test_think_budget_aborts_before_content() -> None:
    from app.model.gateway import ModelResponse, StreamActivity

    aborted: list[int] = []

    async def stream():
        yield StreamActivity(kind="reasoning", text="换一个。" * 80)
        yield "should-not-emit"
        yield ModelResponse(text="should-not-emit")

    result = await consume_complete(
        stream(),
        abort=lambda: aborted.append(1),
        think_char_budget=40,
    )
    assert result.aborted is True
    assert result.text == ""
    assert aborted == [1]
    assert result.think_chars >= 40
