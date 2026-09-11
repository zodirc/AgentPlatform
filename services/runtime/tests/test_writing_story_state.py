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
            "reader_ledger": {
                "believes": ["周婶还在城里"],
                "waiting_for": ["那封信里写了什么"],
            },
            "promises": [
                {"what": "那封信里写了什么", "made_ch": 2, "due": "soon"}
            ],
            "deferred": [
                {"question": "父亲是否知情", "since_ch": 2, "until": "volume_end"}
            ],
            "identity": {"is": ["码头上的人"]},
        },
        workspace_root=tmp_path,
    )
    assert story_state_contract_ready(workspace_root=tmp_path)
    block = format_story_state_block(workspace_root=tmp_path)
    assert "## Story state" in block
    assert "船行月底收船" in block
    assert "那晚的灯是谁点的" in block
    assert "周婶不哭" in block or "不是" in block
    from app.writing.story_state import load_story_state

    state = load_story_state(workspace_root=tmp_path)
    assert "周婶不哭" in (state.get("identity") or {}).get("is_not") or "周婶不哭" in (
        state.get("taboos") or []
    )
    assert (state.get("identity") or {}).get("is")
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


def test_taboos_migrate_into_identity_is_not(tmp_path: Path) -> None:
    from app.writing.regime import save_regime_override
    from app.writing.book_scope import save_book_scope_override
    from app.writing.story_state import load_story_state

    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    save_regime_override(value="author", source="user", workspace_root=tmp_path)
    save_story_state(
        {
            **empty_state(),
            "taboos": ["不写内心独白收尾"],
            "pressures": [{"what": "收船", "trend": "rising"}],
            "info_gaps": [{"what": "灯", "who_knows": ["江照"], "who_doesnt": ["周婶"]}],
        },
        workspace_root=tmp_path,
    )
    state = load_story_state(workspace_root=tmp_path)
    assert "不写内心独白收尾" in (state.get("identity") or {}).get("is_not")
    assert "不写内心独白收尾" in (state.get("taboos") or [])
    assert story_state_contract_ready(workspace_root=tmp_path) is False
    apply_author_delta(
        section_id="ch1",
        deltas=[],
        patch={"identity": {"is": ["码头上的人"]}},
        workspace_root=tmp_path,
    )
    assert story_state_contract_ready(workspace_root=tmp_path) is True


def test_story_state_block_order_and_author_cap(tmp_path: Path) -> None:
    from app.writing.book_scope import save_book_scope_override
    from app.writing.regime import save_regime_override
    from app.writing.text_metrics import visible_chars

    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    save_regime_override(value="author", source="user", workspace_root=tmp_path)
    apply_author_delta(
        section_id="ch4",
        deltas=["江照第一次对周婶撒了谎"],
        patch={
            "pressures": [
                {"what": "船行月底收船", "trend": "rising", "carried_by": "江照"}
            ],
            "open_threads": [
                {"id": "信", "kind": "debt", "planted_ch": 2, "last_touched_ch": 2}
            ],
            "info_gaps": [
                {
                    "who_knows": ["江照"],
                    "who_doesnt": ["周婶"],
                    "what": "那晚的灯是谁点的",
                }
            ],
            "reader_ledger": {"waiting_for": ["那封信里写了什么"]},
            "promises": [{"what": "那封信里写了什么", "made_ch": 1, "due": "soon"}],
            "deferred": [
                {"question": "父亲是否知情", "since_ch": 2, "until": "volume_end"}
            ],
            "identity": {"is": ["码头上的人"], "is_not": ["周婶不哭"]},
        },
        workspace_root=tmp_path,
    )
    block = format_story_state_block(workspace_root=tmp_path)
    order = [
        "加压",
        "欠着的线",
        "谁还不知道",
        "谁在读",
        "逾期许诺",
        "悬置",
        "这本书是/不是",
        "上一章",
    ]
    hits = [block.find(label) for label in order]
    assert all(i >= 0 for i in hits), block
    assert hits == sorted(hits)
    assert visible_chars(block) <= 1200
    fat = "这是一句很长的账本条目，用来撑满帽子。" * 40
    apply_author_delta(
        section_id="ch5",
        deltas=[fat, fat, fat],
        patch={
            "reader_ledger": {
                "believes": [fat[:60]] * 6,
                "suspects": [fat[:60]] * 4,
                "waiting_for": [fat[:60]] * 4,
                "tired_of": [fat[:60]] * 3,
            },
            "deferred": [
                {"question": fat[:80], "since_ch": 1, "until": "volume_end"}
                for _ in range(6)
            ],
        },
        workspace_root=tmp_path,
    )
    capped = format_story_state_block(workspace_root=tmp_path)
    assert visible_chars(capped) <= 1200


def test_author_pass_hint_edit_on_consistency_flags(tmp_path: Path) -> None:
    from app.writing.book_scope import save_book_scope_override
    from app.writing.regime import save_regime_override

    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    save_regime_override(value="author", source="user", workspace_root=tmp_path)
    save_story_state(
        {
            **empty_state(),
            "facts": [
                {"kind": "death", "name": "老钟", "text": "老钟在第 6 章死了", "ch": 6}
            ],
            "deltas": {"6": ["老钟死了"]},
        },
        workspace_root=tmp_path,
    )
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text(
        "# 第七章\n老钟说：把船撑回来。\n",
        encoding="utf-8",
    )
    block = format_story_state_block(workspace_root=tmp_path)
    assert "可以 `/edit`" in block


def test_author_pass_hint_reread_every_five(tmp_path: Path) -> None:
    from app.writing.book_scope import save_book_scope_override
    from app.writing.regime import save_regime_override

    save_book_scope_override(scope="long", source="user", workspace_root=tmp_path)
    save_regime_override(value="author", source="user", workspace_root=tmp_path)
    save_story_state(
        {**empty_state(), "deltas": {"5": ["码头冷了"]}},
        workspace_root=tmp_path,
    )
    block = format_story_state_block(workspace_root=tmp_path)
    assert "可以 `/reread`" in block
