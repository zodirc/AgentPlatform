from __future__ import annotations

import json
from pathlib import Path

from app.writing.signals.surface import has_task_voice
from app.writing.story_state import (
    apply_author_delta,
    apply_mechanical_update,
    bookmark_story_bits,
    consistency_flags,
    empty_state,
    format_story_state_block,
    outline_over_planned,
    save_story_state,
    story_state_contract_ready,
    thread_stale_flags,
)


def test_empty_state_has_no_plan_fields() -> None:
    state = empty_state()
    assert "next_chapter_goal" not in state
    assert "planned_events" not in state
    assert "theme" not in state
    assert state["wild_cards"] == []


def test_mechanical_update_records_death(tmp_path: Path) -> None:
    apply_mechanical_update("老钟落水死了。江照站在码头。", section_id="ch6", workspace_root=tmp_path)
    raw = (tmp_path / ".agent" / "work" / "story_state.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    kinds = [f.get("kind") for f in data.get("facts") or []]
    assert "death" in kinds
    md = (tmp_path / ".agent" / "work" / "story_state.md").read_text(encoding="utf-8")
    assert "老钟" in md


def test_author_delta_and_window_block(tmp_path: Path) -> None:
    apply_author_delta(
        section_id="ch2",
        deltas=["江照第一次对周婶撒了谎"],
        patch={
            "pressures": [
                {"what": "船行月底收船", "trend": "rising", "carried_by": "江照"}
            ],
            "info_gaps": [
                {
                    "who_knows": ["江照"],
                    "who_doesnt": ["周婶"],
                    "what": "那晚的灯是谁点的",
                }
            ],
            "taboos": ["周婶不哭"],
        },
        workspace_root=tmp_path,
    )
    assert story_state_contract_ready(workspace_root=tmp_path)
    block = format_story_state_block(workspace_root=tmp_path)
    assert "## Story state" in block
    assert "船行月底收船" in block
    assert "那晚的灯是谁点的" in block
    assert "应该" not in block
    assert "必须" not in block
    assert "记得" not in block
    assert not has_task_voice(block)
    bits = bookmark_story_bits(workspace_root=tmp_path)
    assert "船行" in bits


def test_consistency_flag_dead_person_speaks(tmp_path: Path) -> None:
    save_story_state(
        {
            **empty_state(),
            "facts": [{"kind": "death", "name": "老钟", "text": "老钟在第 6 章死了", "ch": 6}],
        },
        workspace_root=tmp_path,
    )
    flags = consistency_flags("老钟说：把船撑回来。", section_id="ch7", workspace_root=tmp_path)
    assert flags
    assert flags[0]["kind"] == "fact_death"


def test_thread_stale_after_eight_chapters(tmp_path: Path) -> None:
    save_story_state(
        {
            **empty_state(),
            "open_threads": [
                {
                    "id": "lamp",
                    "planted_ch": 1,
                    "kind": "question",
                    "last_touched_ch": 1,
                }
            ],
        },
        workspace_root=tmp_path,
    )
    stale = thread_stale_flags(current_ch=9, workspace_root=tmp_path)
    assert stale and stale[0]["id"] == "lamp"


def test_outline_over_planned_observes_three_event_chapters() -> None:
    md = (
        "第1章 杀死船主\n"
        "第2章 揭穿假账\n"
        "第3章 决战码头\n"
        "第4章 雨还在下\n"
    )
    assert outline_over_planned(md) is True
    assert outline_over_planned("第1章 码头下雨\n第2章 有人来了\n") is False
