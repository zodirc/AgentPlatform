from __future__ import annotations

import pytest

from app.writing.patch_hygiene import (
    close_span_in_body,
    sanitize_prose_patch,
)
from app.writing.signals.repair import REPAIR_SPAN_MAX, build_repair_span


def test_close_span_includes_leading_speech_tag() -> None:
    body = (
        "蒸汽蒙白了眼镜。他拿毛巾擦了一下，说：「这个还行。」\n"
        "我说：「那当然。」桌上还有划痕。"
    )
    span = "「这个还行。」\n我说：「那当然。」"
    closed = close_span_in_body(body, span, max_chars=REPAIR_SPAN_MAX)
    assert closed.startswith("说：")
    assert closed in body
    assert body.count(closed) == 1


def test_close_span_does_not_truncate_inside_quote() -> None:
    body = "父亲问：「葱买了吗？」\n「买了。」\n「放哪儿？」\n「窗台上。」\n「别忘了放水。」他不再说话。"
    raw = body[body.find("「葱") : body.find("放水") + 2]  # ends inside the last quote
    assert "」" not in raw[-1]
    closed = close_span_in_body(body, raw, max_chars=REPAIR_SPAN_MAX)
    assert closed.endswith("」") or closed.endswith("。")
    assert closed.count("「") == closed.count("」")
    assert closed in body


def test_sanitize_drops_echoed_ask_after_tag() -> None:
    existing = "父亲正在门厅里换鞋，见我拿着东西，问：「买什么了？」\n\n「红薯。」\n"
    old = "「买什么了？」\n\n「红薯。」"
    new = "问：「买了红薯，只有一个。」"
    old2, new2 = sanitize_prose_patch(existing, old, new)
    applied = existing.replace(old2, new2, 1)
    assert "问：问" not in applied
    assert "买了红薯" in applied
    assert applied.count("「") >= 1


def test_sanitize_speech_tag_plus_action_does_not_double_say() -> None:
    existing = (
        "蒸汽把他的眼镜蒙白了。他拿毛巾擦了一下，说：「这个还行。」\n"
        "我说：「那当然。」\n桌上的划痕还在。"
    )
    old = "「这个还行。」\n我说：「那当然。」"
    new = "父亲摸了摸锅盖，说：「这个还行，做饭够用了。」我说当然够用。"
    old2, new2 = sanitize_prose_patch(existing, old, new)
    applied = existing.replace(old2, new2, 1)
    assert "说：父亲摸了摸锅盖，说：" not in applied
    assert "父亲摸了摸锅盖，说：「这个还行，做饭够用了。」" in applied
    assert applied.count("说：「") == 1


def test_sanitize_collapses_doubled_close_quotes() -> None:
    existing = "他便提醒我别忘了给葱根放水。「知道。」"
    old = "「知道。」"
    new = "别忘了给葱根放些水里。」」\n「知道。」"
    _old2, new2 = sanitize_prose_patch(existing, old, new)
    assert "」」" not in new2


@pytest.mark.asyncio
async def test_propose_patch_rejects_dialogue_stripped_to_narration(workspace) -> None:
    from app.tools.core import tools as core

    path = "drafts/manuscript.md"
    target = workspace / path
    target.parent.mkdir(parents=True)
    target.write_text(
        "「进来拿。」\n「我会还。」\n「先记账。」\n「记多久？」\n桌上的秤还在。\n",
        encoding="utf-8",
    )
    result = await core.propose_patch(
        path,
        old_text="「进来拿。」\n「我会还。」\n「先记账。」\n「记多久？」",
        new_text="守义让他先抬脚，告诉他押金先登记，绳子由镇上收。",
    )
    assert result.get("status") == "error"
    assert "对白" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_apply_patch_on_manuscript_does_not_double_say(workspace) -> None:
    from app.tools.core import tools as core

    path = "drafts/manuscript.md"
    target = workspace / path
    target.parent.mkdir(parents=True)
    target.write_text(
        "蒸汽把他的眼镜蒙白了。他拿毛巾擦了一下，说：「这个还行。」\n"
        "我说：「那当然。」\n桌上的划痕还在。\n",
        encoding="utf-8",
    )
    result = await core.apply_patch(
        path,
        new_text="父亲摸了摸锅盖，说：「这个还行，做饭够用了。」我说当然够用。",
        old_text="「这个还行。」\n我说：「那当然。」",
    )
    assert result.get("status") == "applied"
    body = target.read_text(encoding="utf-8")
    assert "说：父亲摸了摸锅盖，说：" not in body
    assert "父亲摸了摸锅盖，说：「这个还行，做饭够用了。」" in body


def test_close_span_does_not_start_at_shuo_period() -> None:
    body = (
        "「绳子给我。」他说。\n\n"
        "一个工人拉住他，指压住地图上的红线。\n"
        "「进来拿。」\n「我会还。」\n「先记账。」\n「记多久？」\n"
    )
    raw = "说。\n\n一个工人拉住他，指压住地图上的红线。\n「进来拿。」"
    closed = close_span_in_body(body, raw, max_chars=REPAIR_SPAN_MAX)
    assert not closed.startswith("说。")
    assert not closed.startswith("指压住")
    assert closed.lstrip().startswith("「")
    assert "进来拿" in closed


def test_build_repair_span_points_at_antithesis() -> None:
    text = (
        "柜台上还温着酒。他擦了擦玻璃。"
        "「电池还能撑一阵。」\n「钟不知道，屋子知道。」他说。"
    )
    span = build_repair_span(
        text,
        penalties=[{"key": "staccato_uniform", "hit": True}],
        net_signal=0.4,
    )
    assert span is not None
    assert "钟不知道" in span["old_text"]
    assert not span["old_text"].startswith("说。")
    assert "对仗" in span["hint"] or "说明书" in span["hint"] or "告诉他" in span["hint"]


def test_prose_patch_block_reason_dialogue_to_narration() -> None:
    from app.writing.patch_hygiene import prose_patch_block_reason

    old = "「进来拿。」\n「我会还。」\n「先记账。」"
    new = "守义让他先抬脚，告诉他押金先登记，绳子由镇上收。"
    assert prose_patch_block_reason(old, new)
    assert prose_patch_block_reason(old, "「押金先登记，绳子镇上收。」") is None


def test_build_repair_span_keeps_closed_quotes() -> None:
    island = "\n".join(["「跑完了？」", "「跑完了。」", "「少了谁？」", "「不知道。」"])
    text = "鲁镇的酒店格局和别处不同。掌柜说：" + island + "柜台上还温着酒。"
    span = build_repair_span(
        text,
        penalties=[{"key": "staccato_uniform", "hit": True}],
        net_signal=0.4,
    )
    assert span is not None
    assert span["old_text"] in text
    assert span["old_text"].count("「") == span["old_text"].count("」")
    assert "跑完了" in span["old_text"]
