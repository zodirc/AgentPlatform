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
    pitches_too_close,
)
from app.writing.excerpt_job import book_level_low, premise_cohesion_low
from app.writing.subject_pool import (
    draw_subjects,
    family_of,
    pool_for,
    request_is_long_novel,
    select_seeds,
)
from app.writing.work_reconstruction import (
    CANDIDATE_SCHEMA,
    build_candidate_context,
    obvious_meta_text,
    parse_candidate,
    parse_card,
    project_candidate_context,
    sample_user_text,
)


_PITCH = (
    "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
    "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
    "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
)
_DISTINCT = [
    "柜台上的账今晚必须对上，否则铺子开不了门。",
    "船要在天亮前离港，她还没决定人留在哪一岸。",
]
_TITLES = ["余烬", "潮汐"]


def _drawn_subject(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("题材："):
            return line.removeprefix("题材：")
    return ""


def _card(title: str, pitch: str | None = None) -> str:
    return json.dumps(
        {"title": title, "pitch": pitch or f"{title} {_PITCH}"},
        ensure_ascii=False,
    )


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
    assert "换个方向" not in blob
    assert "WRITING" not in blob
    assert "WORK STATE" not in blob
    assert "DELIVERY" not in blob
    assert "《人间未醒》" not in blob
    assert "selector" not in blob.lower()
    assert "renderer" not in blob.lower()


def test_genre_label_is_boundary_not_task() -> None:
    assert _genre_label("写一篇长篇都市修真小说") == "都市修真"
    assert _topic_of("写一篇长篇都市修真小说") == "长篇都市修真"


def test_form_is_a_direct_candidate_job() -> None:
    ctx = project_candidate_context("写一篇长篇都市修真小说")
    assert ctx.genre == "都市修真"
    assert ctx.fresh_work is True
    assert build_candidate_context("写一篇长篇都市修真小说") == {
        "genre": "都市修真",
        "fresh_work": True,
    }
    blob = _content_text(
        form_messages(
            "写一篇长篇都市修真小说",
            subject=pool_for("都市修真")[0],
        )
    )
    assert "用户原话：写一篇长篇都市修真小说" in blob
    assert "类型参考：都市修真" in blob
    assert "用户原话优先" in blob
    assert "题材只供参照，不是模板" in blob
    assert "简介按书页上的作品介绍来写" in blob
    assert "不要罗列卖点" in blob
    assert "持续兑现" not in blob
    assert "因果核心" not in blob
    assert "结构不同的落法" not in blob
    assert "不需要寻找更好的方向" not in blob
    assert f"题材：{pool_for('都市修真')[0]}" in blob
    assert "抽签：" not in blob
    assert "均匀取一本" not in blob
    assert "根据用户原话，借题材参照交一本新书的书名和简介" in blob
    assert "只交一本" in blob
    assert "大概是什么样子" not in blob
    assert "不用寻找最优方案" not in blob
    assert "大概成立" not in blob
    assert "请输出 JSON" not in blob
    assert "看起来像一本" not in blob
    assert "150～250字" not in blob
    assert "fresh_work" not in blob
    assert "task = " not in blob
    assert "genre =" not in blob
    assert "focus=ch1" not in blob
    assert "book_scope" not in blob
    assert "work_mode" not in blob
    assert "You are a writing assistant" not in blob
    another = _content_text(
        form_messages(
            "写一篇长篇都市修真小说",
            subject=pool_for("都市修真")[1],
        )
    )
    assert "以下作品已经出现过" not in another
    assert "结构签名" not in another
    assert pool_for("都市修真")[1] in another
    assert "先写正在发生的事" not in blob
    _banned_theory(blob)
    assert "[writing_context]" not in blob
    msgs = form_messages("写一篇长篇都市修真小说")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"


def test_projection_ignores_workspace_writing_state(tmp_path) -> None:
    (tmp_path / "outline.md").write_text("focus=ch1\nfragment=plot_progress\n", encoding="utf-8")
    (tmp_path / ".agent" / "work").mkdir(parents=True)
    (tmp_path / ".agent" / "work" / "author_state.md").write_text("旧书", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text("正文", encoding="utf-8")
    ctx = project_candidate_context(
        "写一篇长篇都市修真小说",
        workspace_root=tmp_path,
    )
    assert ctx.genre == "都市修真"
    blob = _content_text(form_messages("写一篇长篇都市修真小说"))
    assert "focus=ch1" not in blob
    assert "manuscript" not in blob
    assert "旧书" not in blob


def test_owned_subject_pool_is_the_draw_support() -> None:
    pool = pool_for("都市修真")
    assert 72 <= len(pool) <= 96
    assert len(set(pool)) == len(pool)
    assert "庆尘" not in "".join(pool)
    for index, left in enumerate(pool):
        assert book_level_low(left) is False
        assert premise_cohesion_low(left) is False
        for right in pool[index + 1 :]:
            assert left not in right
            assert right not in left
    drawn = draw_subjects("都市修真", 2)
    assert len(set(drawn)) == 2
    assert set(drawn) <= set(pool)
    assert family_of(drawn[0]) != family_of(drawn[1])
    assert draw_subjects("历史", 2) == []
    assert draw_subjects("写一篇历史小说", 2) == []
    assert draw_subjects("写一篇都市故事", 2) == []
    assert draw_subjects("写一部历史小说", 2) == []
    urban_ask = "我期望你给我的是一本，传统都市+一些异能（只有主角有系统）的小说"
    assert draw_subjects(urban_ask, 2) == []
    assert pool_for("都市修真") == pool_for("都市异能") == pool_for("都市玄幻")
    assert draw_subjects("都市玄幻", 2)
    assert len(draw_subjects("写一篇长篇的异能小说", 2)) == 2
    assert select_seeds("写一部历史小说", 2) == []
    assert request_is_long_novel("写一部历史小说") is True


def test_specific_requests_bypass_random_references() -> None:
    directed = (
        "写一本类似滚开的加点武道系统文",
        "参考全职猎人的念能力做一套能力体系",
        "世界很平凡，只有主角有异能",
        "我期望是，更金手指，世界本平凡的那种，只有主角有一个超级系统这样",
        "系统、金手指、爽文的异能小说",
    )
    assert all(select_seeds(request, 2) == [] for request in directed)
    assert len(select_seeds("写一本系统文", 2)) == 2
    urban = select_seeds("写一本都市文", 2)
    assert len(urban) == 2
    assert {seed.shelf for seed in urban} <= {
        "现代人生",
        "都市生活",
        "都市隐秘",
        "都市异变",
    }


@pytest.mark.asyncio
async def test_missing_pool_does_not_call_the_model() -> None:
    async def complete(messages):
        raise AssertionError(messages)

    pair = await sample_independent_pair("写一篇历史小说", complete=complete)
    assert pair == []


@pytest.mark.asyncio
async def test_generic_ability_request_reaches_model_with_seed_and_raw_request() -> None:
    seen: list[str] = []

    async def complete(messages):
        text = _content_text(messages)
        seen.append(text)
        return _card(_TITLES[len(seen) - 1], _DISTINCT[len(seen) - 1])

    pair = await sample_independent_pair("写一篇长篇的异能小说", complete=complete)
    assert len(pair) == 2
    assert len(seen) == 2
    assert all("用户原话：写一篇长篇的异能小说" in text for text in seen)
    assert all(_drawn_subject(text) for text in seen)
    assert len({_drawn_subject(text) for text in seen}) == 2


@pytest.mark.asyncio
async def test_specific_system_request_reaches_model_without_conflicting_seed() -> None:
    request = "我期望是，更金手指，世界本平凡的那种，只有主角有一个超级系统这样"
    seen: list[str] = []

    async def complete(messages):
        text = _content_text(messages)
        seen.append(text)
        return _card(_TITLES[len(seen) - 1], _DISTINCT[len(seen) - 1])

    pair = await sample_independent_pair(request, complete=complete)
    assert len(pair) == 2
    assert len(seen) == 2
    assert all(f"用户原话：{request}" in text for text in seen)
    assert all("题材：" not in text for text in seen)
    assert all("大乾北地" not in text and "录音" not in text for text in seen)


@pytest.mark.asyncio
async def test_other_long_genre_samples_without_a_fake_subject() -> None:
    calls = 0

    async def complete(messages):
        nonlocal calls
        text = _content_text(messages)
        assert "用户原话：写一篇长篇历史小说" in text
        assert "类型参考：历史" in text
        assert "题材：" not in text
        assert "只继承用户这句话" not in text
        calls += 1
        return _card(_TITLES[calls - 1], _DISTINCT[calls - 1])

    pair = await sample_independent_pair("写一篇长篇历史小说", complete=complete)
    assert len(pair) == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_close_second_card_is_resampled_once() -> None:
    shared = "他在夜里检修城中的阵法，工资交给房租，进阶要付出代价。" * 2
    calls = 0
    subjects: list[str] = []

    async def complete(messages):
        nonlocal calls
        calls += 1
        text = _content_text(messages)
        subjects.append(_drawn_subject(text))
        assert "结构族：" not in text
        assert "至少在两个维度上不同" not in text
        if calls == 1:
            return _card("余烬", shared)
        if calls == 2:
            return _card("潮汐", shared)
        return _card("潮汐", "船要离港，人还留在北岸，这件事只跟这一船人有关。")

    pair = await sample_independent_pair("写一篇长篇都市修真小说", complete=complete)
    assert calls == 3
    assert pitches_too_close(shared, shared) is True
    assert [it["title"] for it in pair] == ["余烬", "潮汐"]
    assert shared not in pair[1]["pitch"]
    assert len(set(subjects)) == 3


def test_choice_turn_keeps_the_named_genre() -> None:
    named = "写一篇长篇的都市修真小说"
    assert sample_user_text("我要其他的", [named]) == named
    assert sample_user_text("我看看", [named]) == named
    assert sample_user_text(named, ["写一篇历史小说"]) == named
    history = "写一篇历史小说"
    assert sample_user_text("我看看", [history]) == history


def test_parse_card_and_meta_guard() -> None:
    card = parse_card(_card("余烬"))
    assert card is not None
    assert card["title"] == "余烬"
    assert "灾变之后" in card["pitch"]
    assert parse_candidate("太短了") is None
    assert parse_candidate(_card("余烬", "我觉得这个故事可以很长。")) is None
    assert obvious_meta_text("我觉得这个故事可以很长。") is True
    assert obvious_meta_text(_PITCH) is False
    assert parse_card(_card("烬")) is None
    assert parse_card(_card("灵潮纪元：地铁末班车")) is not None
    assert parse_card(_card("这是一个过长的书名还要再长一些才行")) is None


def test_form_budget_is_medium_not_30k() -> None:
    form = form_generation()
    assert form.max_output_tokens == _FORM_MAX_OUTPUT_TOKENS
    assert _FORM_MAX_OUTPUT_TOKENS <= 2048
    assert _FORM_THINK_CHAR_BUDGET <= 8000
    assert form.tool_choice == "none"
    assert form.thinking_enabled is False
    assert form.reasoning_effort == "none"
    assert form.response_schema == CANDIDATE_SCHEMA
    assert form.response_schema["required"] == ["title", "pitch"]
    assert _SAMPLE_POOL == 2


@pytest.mark.asyncio
async def test_two_independent_sketches_then_cards() -> None:
    seen: list[str] = []
    form_i = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        assert "《人间未醒》" not in text
        assert "previous_attempt_discarded" not in text
        assert "已经冻结的候选概貌" not in text
        assert "渡劫要报备" not in text
        seen.append(text)
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], f"{_TITLES[idx]} {_DISTINCT[idx]}")

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        held=[{"title": "渡劫要报备", "opening": "旧卡"}],
    )
    assert sorted(it["title"] for it in pair) == ["余烬", "潮汐"]
    assert {it["pitch"][:2] for it in pair} == {"余烬", "潮汐"}
    assert form_i == 2
    assert len(seen) == 2
    drawn = [_drawn_subject(s) for s in seen]
    assert len(set(drawn)) == 2
    assert set(drawn) <= set(pool_for("都市修真"))
    for text, subject in zip(seen, drawn):
        assert "抽签：" not in text
        assert "均匀取一本" not in text
        for other in drawn:
            if other != subject:
                assert other not in text
    assert not any("《余烬》" in s or "已经写过" in s for s in seen)


@pytest.mark.asyncio
async def test_missing_title_retries_this_sample_once() -> None:
    form_i = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal form_i
        async with lock:
            idx = form_i
            form_i += 1
        if idx == 0:
            return "短。"
        slot = min(idx - 1, 1)
        return _card(_TITLES[slot], _DISTINCT[slot])

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        need=2,
    )
    assert len(pair) == 2
    assert form_i == 3
    assert {it["title"] for it in pair} == {"余烬", "潮汐"}


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
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal form_i
        await cs._emit_thinking_delta("<form>")
        await asyncio.sleep(0.01)
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], _DISTINCT[idx])

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        need=2,
    )
    assert len(pair) == 2
    assert deltas.count("\n—— 题材池 ——\n") == 1
    assert deltas.count("\n—— 独立采样 ——\n") == 2
    stages = [d for d in deltas if d.startswith("<")]
    assert stages == ["<form>", "<form>"]


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
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal form_i
        text = _content_text(messages)
        assert "以下作品已经出现过" not in text
        assert "结构签名" not in text
        assert "渡劫要报备" not in text
        assert "城隍夜巡" not in text
        assert "题材：渡劫要报备" not in text
        assert "题材：城隍夜巡" not in text
        assert "previous_attempt_discarded" not in text
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], f"NEW{idx} {_DISTINCT[idx]}")

    result = await propose_book_candidates(
        [],
        turn_id=turn_id,
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "ok"
    titles = [it["title"] for it in result["items"]]
    assert set(titles) == {"余烬", "潮汐"}
    assert "渡劫要报备" not in titles
    assert "城隍夜巡" not in titles
    assert all(it["pitch"].startswith("NEW") for it in result["items"])
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
        return _card("渡劫要报备")

    result = await propose_book_candidates(
        [],
        turn_id=turn_id,
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "error"
    assert result.get("stop_retry") is True
    assert result.get("fresh_retry") is False
    assert "渡劫要报备" not in json.dumps(result, ensure_ascii=False)
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_slot_ids_in_old_pond_do_not_drop_new_samples(workspace, monkeypatch) -> None:
    from uuid import uuid4

    from app.settings import settings
    from app.tools.core.writing_tools import propose_book_candidates
    from app.writing.opening_ponds import clear_pond_rejects, save_opening_ponds

    monkeypatch.setattr(settings, "ponds_excerpt_gate", True)
    clear_pond_rejects()
    turn_id = uuid4()
    save_opening_ponds(
        [
            {"id": "c01", "title": "c01", "opening": "旧槽位残留。"},
            {"id": "c02", "title": "c02", "opening": "另一槽位残留。"},
        ]
    )
    form_i = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal form_i
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], f"NEW{idx} {_DISTINCT[idx]}")

    result = await propose_book_candidates(
        [],
        turn_id=turn_id,
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "ok"
    assert set(it["title"] for it in result["items"]) == {"余烬", "潮汐"}
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_sample_one_returns_title_and_pitch(caplog) -> None:
    calls = 0

    async def complete(messages):
        nonlocal calls
        calls += 1
        text = _content_text(messages)
        assert "《人间未醒》" not in text
        return _card("余烬")

    with caplog.at_level(logging.INFO, logger="app.writing.candidate_sample"):
        item = await sample_one_candidate("写一篇长篇都市修真小说", complete=complete)
    assert item is not None
    assert item["title"] == "余烬"
    assert item["pitch"].startswith("余烬")
    assert calls == 1
    traces = [
        json.loads(rec.getMessage().removeprefix("candidate_trace "))
        for rec in caplog.records
        if rec.getMessage().startswith("candidate_trace ")
    ]
    assert traces[-1]["title"] == "余烬"
    assert traces[-1]["opening"].startswith("余烬")


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


@pytest.mark.asyncio
async def test_consume_complete_reads_structured_tool_call() -> None:
    from app.model.gateway import ModelResponse

    async def stream():
        yield ModelResponse(
            text="",
            tool_calls=[
                {
                    "id": "c1",
                    "name": "book_candidate",
                    "input": {"title": "余烬", "pitch": _PITCH},
                }
            ],
        )

    result = await consume_complete(stream())
    parsed = parse_card(result.text)
    assert parsed is not None
    assert parsed["title"] == "余烬"
    assert "灾变之后" in parsed["pitch"]


@pytest.mark.asyncio
async def test_format_fail_does_not_spawn_third_sample() -> None:
    calls = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal calls
        async with lock:
            calls += 1
        return "短。"

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
    )
    assert pair == []
    assert calls == 4
