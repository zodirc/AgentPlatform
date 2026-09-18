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
    CANDIDATE_SCHEMA,
    build_candidate_context,
    obvious_meta_text,
    parse_candidate,
    parse_card,
    project_candidate_context,
)


_PITCH = (
    "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
    "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
    "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
)
_TITLES = ["余烬", "潮汐"]


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
    blob = _content_text(form_messages("写一篇长篇都市修真小说"))
    assert "题材：都市修真" in blob
    assert "根据题材直接生成一个小说候选" in blob
    assert "只交一个结果" in blob
    assert "不需要寻找更好的方向" in blob
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
        seen.append(text)
        assert "《人间未醒》" not in text
        assert "previous_attempt_discarded" not in text
        assert "已经冻结的候选概貌" not in text
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], f"{_TITLES[idx]} {_PITCH}")

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        held=[{"title": "渡劫要报备", "opening": "旧卡"}],
    )
    assert sorted(it["title"] for it in pair) == ["余烬", "潮汐"]
    assert {it["pitch"][:2] for it in pair} == {"余烬", "潮汐"}
    assert form_i == 2
    assert len(seen) == 2
    assert len(set(seen)) == 1
    assert not any("渡劫要报备" in s for s in seen)


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
        return _card(_TITLES[min(idx - 1, 1)])

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
        return _card(_TITLES[idx])

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        need=2,
    )
    assert len(pair) == 2
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
        assert "渡劫要报备" not in text
        assert "城隍夜巡" not in text
        assert "previous_attempt_discarded" not in text
        async with lock:
            idx = form_i
            form_i += 1
        return _card(_TITLES[idx], f"NEW{idx} {_PITCH}")

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
        return _card(_TITLES[idx], f"NEW{idx} {_PITCH}")

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
