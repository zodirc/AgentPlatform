"""Tests for large prose duplicate collapse and worsening-patch rejection."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.tools.core import tools as core
from app.writing.prose_dedupe import (
    DUP_PARA_MIN_VISIBLE,
    collapse_duplicate_paragraphs,
    excess_large_duplicate_paragraphs,
    patch_worsens_duplicate,
)
from app.writing.text_metrics import visible_chars


_LONG_A = (
    "回川，是父亲给他取的乳名，意思是水流出去，总有一天还会回来。"
    "这个名字没有写进户册，也没有写进渡籍，陆青禾失踪之后，家里便只剩她还叫过。"
)
_LONG_B = (
    "泥滩上的铁签翻了过来，黑泥从签面滑落，露出两个字：陆回川。"
    "陆沉舟的呼吸停了一瞬。那不是刻上去的，字迹像被水泡开的墨，浮在铁面上。"
)


def test_long_fixture_meets_threshold() -> None:
    assert visible_chars(_LONG_A) >= DUP_PARA_MIN_VISIBLE
    assert visible_chars(_LONG_B) >= DUP_PARA_MIN_VISIBLE


def test_collapse_keeps_first_large_paragraph() -> None:
    body = f"前缀。\n\n{_LONG_A}\n\n{_LONG_B}\n\n{_LONG_A}\n\n{_LONG_B}\n\n收束。\n"
    out, removed = collapse_duplicate_paragraphs(body)
    assert removed == 2
    assert out.count(_LONG_A) == 1
    assert out.count(_LONG_B) == 1
    assert "前缀。" in out
    assert "收束。" in out
    assert excess_large_duplicate_paragraphs(out) == 0


def test_collapse_ignores_short_refrain() -> None:
    body = "开场。\n\n咚。\n\n中间。\n\n咚。\n\n收束。\n"
    out, removed = collapse_duplicate_paragraphs(body)
    assert removed == 0
    assert out.count("咚。") == 2


def test_patch_worsens_when_new_text_already_elsewhere() -> None:
    body = f"开场。\n\n{_LONG_A}\n\n对白段。\n"
    err = patch_worsens_duplicate(body, "对白段。", _LONG_A)
    assert err is not None
    assert "patch_worsens_duplicate" in err


def test_patch_allows_delete_duplicate() -> None:
    body = f"开场。\n\n{_LONG_A}\n\n{_LONG_A}\n\n收束。\n"
    assert patch_worsens_duplicate(body, _LONG_A, "") is None


def test_patch_allows_in_place_unique_rewrite() -> None:
    body = f"开场。\n\n{_LONG_A}\n\n收束。\n"
    new = (
        "回川这两个字没有写进户册。铁签翻过来时，陆沉舟只把签面按进泥里，没有出声。"
    )
    assert visible_chars(new) >= DUP_PARA_MIN_VISIBLE
    assert patch_worsens_duplicate(body, _LONG_A, new) is None


@pytest.mark.asyncio
async def test_propose_patch_rejects_worsening_duplicate(workspace) -> None:
    path = "drafts/manuscript.md"
    target = workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# ch1\n\n{_LONG_A}\n\n「你看错了。」\n\n收束。\n",
        encoding="utf-8",
    )
    result = await core.propose_patch(
        path,
        old_text="「你看错了。」",
        new_text=_LONG_A,
        summary="误把对白换成已有揭示",
    )
    assert result.get("error") == "patch_worsens_duplicate"
    assert result.get("status") == "error"


@pytest.mark.asyncio
async def test_apply_patch_collapses_existing_duplicates(workspace) -> None:
    path = "drafts/manuscript.md"
    target = workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# ch1\n\n{_LONG_A}\n\n{_LONG_A}\n\n旧句。\n",
        encoding="utf-8",
    )
    result = await core.apply_patch(
        path=path,
        old_text="旧句。",
        new_text="新句。",
    )
    assert result.get("status") == "applied"
    assert int(result.get("duplicates_collapsed") or 0) >= 1
    text = target.read_text(encoding="utf-8")
    assert text.count(_LONG_A) == 1


@pytest.mark.asyncio
async def test_rewrite_window_collapses_broadcast_paragraph_dups(workspace) -> None:
    turn_id = uuid4()
    path = workspace / "drafts" / "manuscript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    old_span = _LONG_A
    # Blank-line separated so broadcast creates two large paragraphs.
    path.write_text(
        f"# ch1\n\n前文\n\n{old_span}\n\n后文\n\n{old_span}\n",
        encoding="utf-8",
    )
    manifest_dir = workspace / ".agent" / "work" / "turns"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{turn_id}.json").write_text(
        json.dumps(
            {
                "section_drafts": {
                    "ch1": {
                        "repair_span": {
                            "key": "staccato_uniform",
                            "old_text": old_span,
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    replacement = (
        "河工把渡税和闸旗的规矩说清楚，又指了指外头正在退的水线，"
        "让陆沉舟把最后一栏写完再收工。"
    )
    assert visible_chars(replacement) >= DUP_PARA_MIN_VISIBLE
    result = await core.draft_section(
        "ch1",
        replacement,
        turn_id=turn_id,
        mode="rewrite_window",
    )
    assert result.get("status") == "drafted"
    text = path.read_text(encoding="utf-8")
    assert old_span not in text
    assert text.count(replacement) == 1
    assert int(result.get("duplicates_collapsed") or 0) >= 1
