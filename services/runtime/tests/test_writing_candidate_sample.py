from __future__ import annotations

import asyncio
import json

import pytest

from app.writing.candidate_sample import (
    _content_text,
    compress_messages,
    form_messages,
    parse_title_pitch,
    sample_independent_pair,
    sample_one_candidate,
)


_GOOD_A = (
    "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
    "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
    "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
)
_GOOD_B = (
    "四万年前，人类发现了修真之路。四万年后，修真已经成为这个时代最重要的力量。"
    "李耀出生在大荒，靠捡破烂为生，却想成为最出色的炼器师。"
    "一个生活在修真时代底层的少年，就这样走上了自己的修真之路。"
)
_OCCUPATION = (
    "周记推拿店打烊后，林哥把客人背上那张符纸揭下来。"
    "灵气顺着掌心进来，这门手艺从此能把人的寿元往回推。"
    "他不敢跟伙计说，只把这件事按在自己手底下。"
    "明天店门还要开，他已经知道有人会再来求这一手。"
)


def test_form_context_is_candidate_mode_not_prose_rules() -> None:
    blob = _content_text(form_messages("写一篇长篇都市修真小说"))
    assert "### CANDIDATE MODE" in blob
    assert "### TARGET SHELF" in blob
    assert "《诡秘之主》" in blob
    assert "写一篇长篇都市修真小说" in blob
    assert "先写正在发生的事。" not in blob
    assert "环境是人物正站着的那块地方长出来的" not in blob
    assert "主角已经有" not in blob
    assert "两本不同的书" not in blob
    assert "当成构思起点" in blob


def test_compress_is_seed_only() -> None:
    blob = _content_text(compress_messages("SEED-ONLY-BOOK-AAAA"))
    assert "SEED-ONLY-BOOK-AAAA" in blob
    assert "### TARGET SHELF" not in blob
    assert "《诡秘之主》" not in blob
    assert "先写正在发生的事" not in blob
    assert "压成" in blob


def test_parse_title_pitch_json_and_fence() -> None:
    raw = '前言\n```json\n{"title": "余烬", "pitch": "' + _GOOD_A + '"}\n```'
    parsed = parse_title_pitch(raw)
    assert parsed is not None
    assert parsed["title"] == "余烬"
    assert parsed["pitch"].startswith("灾变之后")


@pytest.mark.asyncio
async def test_two_samples_do_not_share_context() -> None:
    seen: list[str] = []
    compress_i = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal compress_i
        text = _content_text(messages)
        seen.append(text)
        if "已经形成的一本书" in text:
            async with lock:
                idx = compress_i
                compress_i += 1
            title = "余烬" if idx == 0 else "潮汐"
            pitch = _GOOD_A if idx == 0 else _GOOD_B
            return json.dumps({"title": title, "pitch": pitch}, ensure_ascii=False)
        form_n = sum(1 for s in seen if "已经形成的一本书" not in s)
        return "SEED-A-UNIQUE book one engine" if form_n == 1 else "SEED-B-UNIQUE book two engine"

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        gate=False,
    )
    assert len(pair) == 2
    titles = {it["title"] for it in pair}
    assert titles == {"余烬", "潮汐"}
    form_blobs = [s for s in seen if "已经形成的一本书" not in s]
    compress_blobs = [s for s in seen if "已经形成的一本书" in s]
    assert len(form_blobs) == 2
    assert len(compress_blobs) == 2
    assert all("SEED-A-UNIQUE" not in s and "SEED-B-UNIQUE" not in s for s in form_blobs)
    assert sum("SEED-A-UNIQUE" in s for s in compress_blobs) == 1
    assert sum("SEED-B-UNIQUE" in s for s in compress_blobs) == 1
    assert not any("SEED-A-UNIQUE" in s and "SEED-B-UNIQUE" in s for s in seen)


@pytest.mark.asyncio
async def test_failed_card_is_resampled_without_failure_signal() -> None:
    compress_i = 0
    lock = asyncio.Lock()
    seen: list[str] = []

    async def complete(messages):
        nonlocal compress_i
        text = _content_text(messages)
        seen.append(text)
        if "已经形成的一本书" not in text:
            return "a long serial already formed in this isolated sample"
        async with lock:
            idx = compress_i
            compress_i += 1
        if idx < 2:
            return json.dumps(
                {"title": "周记推拿", "pitch": _OCCUPATION},
                ensure_ascii=False,
            )
        title = "余烬" if idx == 2 else "潮汐"
        pitch = _GOOD_A if idx == 2 else _GOOD_B
        return json.dumps({"title": title, "pitch": pitch}, ensure_ascii=False)

    pair = await sample_independent_pair(
        "写一篇长篇都市修真小说",
        complete=complete,
        gate=True,
    )
    titles = {it["title"] for it in pair}
    assert titles == {"余烬", "潮汐"}
    blob = "\n".join(seen)
    assert "ponds_occupation" not in blob
    assert "occupation_centrality" not in blob
    assert "这组候选作废" not in blob


@pytest.mark.asyncio
async def test_propose_uses_independent_sample_hook(workspace, monkeypatch) -> None:
    from uuid import uuid4

    from app.settings import settings
    from app.tools.core.writing_tools import propose_book_candidates
    from app.writing.opening_ponds import clear_pond_rejects

    monkeypatch.setattr(settings, "ponds_excerpt_gate", True)
    clear_pond_rejects()
    compress_i = 0
    lock = asyncio.Lock()

    async def complete(messages):
        nonlocal compress_i
        text = _content_text(messages)
        if "已经形成的一本书" not in text:
            assert "先写正在发生的事" not in text
            assert "### CANDIDATE MODE" in text
            return "formed serial seed"
        async with lock:
            idx = compress_i
            compress_i += 1
        title = "余烬" if idx == 0 else "潮汐"
        pitch = _GOOD_A if idx == 0 else _GOOD_B
        return json.dumps({"title": title, "pitch": pitch}, ensure_ascii=False)

    result = await propose_book_candidates(
        [],
        turn_id=uuid4(),
        turn_user_text="写一篇长篇都市修真小说",
        sample_complete=complete,
    )
    assert result["status"] == "ok"
    titles = {it["title"] for it in result["items"]}
    assert titles == {"余烬", "潮汐"}
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_sample_one_is_form_then_compress() -> None:
    stages: list[str] = []

    async def complete(messages):
        text = _content_text(messages)
        if "已经形成的一本书" in text:
            stages.append("compress")
            assert stages == ["form", "compress"]
            return json.dumps({"title": "余烬", "pitch": _GOOD_A}, ensure_ascii=False)
        stages.append("form")
        return "this is the book as a serial, not a one-scene hook"

    item = await sample_one_candidate("写一篇长篇都市修真小说", complete=complete)
    assert item is not None
    assert item["title"] == "余烬"
    assert stages == ["form", "compress"]


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
