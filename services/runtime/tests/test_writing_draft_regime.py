from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.tools.core import tools as core
from app.writing.regime import save_regime_override
from app.writing.story_state import load_story_state

_COMMIT = {
    "time_order": "mid_flashback",
    "subplot": "parallel_theme",
    "resolution_agency": "unresolved",
    "moral_polarity": "ambivalent",
    "affect_mode": "named",
    "locations": "2+",
}


def _chapter(n: int = 40) -> str:
    return (
        "鲁镇的酒店的格局，是和别处不同的：都是当街一个曲尺形的大柜台，"
        "柜里面预备着热水，可以随时温酒。孔乙己便排出九文大钱。"
    ) * n


@pytest.mark.asyncio
async def test_author_draft_result_has_no_signals(workspace: Path) -> None:
    save_regime_override(value="author", source="user", workspace_root=workspace)
    result = await core.draft_section(
        "ch2",
        _chapter(),
        turn_id=uuid4(),
        turn_user_text="写一章长篇第二章 作者模式",
        fragment="mixed",
        choices=_COMMIT,
    )
    assert result["status"] == "drafted"
    assert result["regime"] == "author"
    assert "writing_signals" not in result
    assert "penalties" not in result
    assert "repair_span" not in result
    assert "rewrite_policy" not in result
    assert "visible_chars" in result
    assert result.get("target_range") == [1800, 4500]
    assert "length_short" not in result
    assert "低于门槛" not in str(result.get("summary") or "")


@pytest.mark.asyncio
async def test_strict_draft_keeps_signals(workspace: Path) -> None:
    result = await core.draft_section(
        "ch1",
        _chapter(8),
        turn_id=uuid4(),
        turn_user_text="写一篇短篇小说",
        fragment="mixed",
        narrative_commitment=_COMMIT,
    )
    assert result["status"] == "drafted"
    assert result.get("regime") == "strict"
    assert isinstance(result.get("writing_signals"), dict)


@pytest.mark.asyncio
async def test_author_full_redraft_keeps_previous(workspace: Path) -> None:
    save_regime_override(value="author", source="user", workspace_root=workspace)
    turn_id = uuid4()
    first = await core.draft_section(
        "ch2",
        _chapter(),
        turn_id=turn_id,
        turn_user_text="写一章长篇第二章 作者模式",
        fragment="mixed",
        choices=_COMMIT,
    )
    assert first["status"] == "drafted"
    second = await core.draft_section(
        "ch2",
        _chapter() + "整章重交一遍。",
        turn_id=turn_id,
        turn_user_text="写一章长篇第二章 作者模式",
        fragment="mixed",
        choices=_COMMIT,
    )
    assert second["status"] == "drafted"
    assert second.get("previous_kept")
    draft = (workspace / "drafts" / "manuscript.md").read_text(encoding="utf-8")
    assert "整章重交一遍" in draft


@pytest.mark.asyncio
async def test_swerve_records_debt(workspace: Path) -> None:
    save_regime_override(value="author", source="user", workspace_root=workspace)
    result = await core.draft_section(
        "ch3",
        _chapter(12),
        turn_id=uuid4(),
        turn_user_text="写一章长篇第三章 作者模式",
        fragment="mixed",
        choices=_COMMIT,
        swerve=True,
    )
    assert result["status"] == "drafted"
    state = load_story_state(workspace_root=workspace)
    assert 3 in [int(x) for x in (state.get("swerves") or [])]
