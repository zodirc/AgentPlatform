from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.opening_ponds import (
    MORE_PONDS_MESSAGE,
    format_select_pond_message,
    load_opening_ponds,
    normalize_pond_items,
    opening_choice_block,
    should_gate_opening_choice,
)
from app.writing.outline_phase import wants_opening_candidates


def test_wants_opening_candidates_browse_and_commit() -> None:
    assert wants_opening_candidates("写一章长篇修真，我看看") is True
    assert wants_opening_candidates(MORE_PONDS_MESSAGE) is True
    assert (
        wants_opening_candidates("按开篇候选「早高峰系统」写第一章。") is False
    )


def test_opening_choice_block_asks_self_discovered_ability() -> None:
    block = opening_choice_block()
    assert "capability" in block.lower()
    assert "themselves" in block.lower()
    assert "window-death" in block


def test_should_gate_opening_choice_when_browsing() -> None:
    assert should_gate_opening_choice(
        "写一章长篇修真小说的第一章, 现代都市题材，我看看",
        outline="",
        tool_names=["propose_opening_ponds", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "按开篇候选「早高峰系统」写第一章。",
        outline="",
        tool_names=["propose_opening_ponds", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "写一章长篇修真，我看看",
        outline="",
        tool_names=["draft_section"],
    )


def test_normalize_pond_items_requires_two() -> None:
    assert normalize_pond_items([{"title": "only"}]) == [
        {
            "id": "pond-1",
            "title": "only",
            "who": "",
            "where": "",
            "want": "",
            "chapter_job": "",
            "summary": "",
        }
    ]


@pytest.mark.asyncio
async def test_propose_opening_ponds_saves_and_awaits(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds(
        [
            {
                "title": "早高峰系统",
                "who": "保安周石",
                "where": "大堂闸机",
                "want": "系统换班",
                "chapter_job": "当场进场",
            },
            {
                "title": "午饭功法",
                "who": "林浅",
                "where": "食堂",
                "want": "口诀入体",
            },
        ],
        summary="两份近池",
    )
    assert result["awaiting_choice"] is True
    assert result["status"] == "ok"
    assert len(result["items"]) == 2
    saved = load_opening_ponds(workspace_root=workspace)
    assert saved is not None
    assert saved["items"][0]["title"] == "早高峰系统"
    msg = format_select_pond_message(saved["items"][0])
    assert "按开篇候选「早高峰系统」" in msg
    assert wants_opening_candidates(msg) is False


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_one(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds([{"title": "only", "who": "a", "where": "b", "want": "c"}])
    assert result["status"] == "error"
    assert result["error"] == "need_two_ponds"
