from __future__ import annotations

from pathlib import Path

from app.tools.core.writing_tools import _silence_wild_card_signals
from app.writing.author_notes import record_user_verdict
from app.writing.editor_notes import build_editor_note_lines
from app.writing.story_state import (
    apply_author_delta,
    record_wild_card,
    wild_card_available,
    wild_card_without_consequence,
)


def test_wild_card_quota_one_per_volume(tmp_path: Path) -> None:
    ok, _ = wild_card_available("ch3", workspace_root=tmp_path)
    assert ok is True
    record_wild_card("ch3", workspace_root=tmp_path)
    ok2, reason = wild_card_available("ch4", workspace_root=tmp_path)
    assert ok2 is False
    assert "wild_card" in reason
    ok3, _ = wild_card_available("ch6", workspace_root=tmp_path)
    assert ok3 is True


def test_silence_wild_card_signals_keeps_only_l0() -> None:
    block = {
        "penalties": [
            {"key": "staccato_uniform", "hit": True, "delta": -0.18},
            {"key": "meta_knowing_high", "hit": True, "delta": -0.06},
        ],
        "rewards": [{"key": "scene_ratio_high", "delta": 0.08}],
        "repair_span": {"old_text": "「来。」"},
        "net_signal": 0.4,
    }
    out = _silence_wild_card_signals(block)
    keys = {p["key"] for p in out["penalties"]}
    assert keys == {"staccato_uniform"}
    assert out["rewards"] == []
    assert "repair_span" not in out
    assert out["wild_card"] is True
    assert out["l1_silenced"] is True


def test_wild_card_without_consequence_and_editor_line(tmp_path: Path) -> None:
    record_wild_card("ch2", workspace_root=tmp_path)
    apply_author_delta(
        section_id="ch3",
        deltas=["江照去了城里"],
        workspace_root=tmp_path,
    )
    unpaid = wild_card_without_consequence(current_ch=3, workspace_root=tmp_path)
    assert unpaid == 2
    lines = build_editor_note_lines(section_id="ch3", wild_unpaid=unpaid)
    assert any("第 2 章的越轨还没有后果" in ln for ln in lines)
    apply_author_delta(
        section_id="ch4",
        deltas=["第 2 章卖铜铃的后果到了"],
        workspace_root=tmp_path,
    )
    assert wild_card_without_consequence(current_ch=4, workspace_root=tmp_path) is None


def test_user_verdict_writes_author_notes(tmp_path: Path) -> None:
    record_user_verdict(
        section_id="ch7",
        kind="wild_card",
        action="keep",
        workspace_root=tmp_path,
    )
    text = (tmp_path / ".agent" / "work" / "author_notes.md").read_text(encoding="utf-8")
    assert "用户裁决" in text
    assert "保留" in text
