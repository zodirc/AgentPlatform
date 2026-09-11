from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.bootstrap import build_registry, tool_scope
from app.scenarios.registry import ScenarioRegistry
from app.writing.editor import (
    format_typed_editor_block,
    normalize_editor_report,
    save_editor_report,
)
from app.writing.editor_notes import format_editor_notes_block, write_editor_notes
from app.writing.reread import should_gate_editor_phase


def test_editor_gate_phrases() -> None:
    assert should_gate_editor_phase("/edit")
    assert should_gate_editor_phase("[edit] 看看第七章")
    assert should_gate_editor_phase("编辑看看第 7 章")
    assert not should_gate_editor_phase("写第七章")


def test_editor_drops_howto_evidence(tmp_path: Path) -> None:
    report = normalize_editor_report(
        section_id="ch7",
        flags=[
            {
                "type": "continuity_break",
                "where": "ch7 第三段",
                "evidence": "第 3 章周婶已出城；本章在铺子里",
                "severity": "hard",
            },
            {
                "type": "identity_drift",
                "where": "ch7",
                "evidence": "应该改成她不说话",
                "severity": "soft",
            },
        ],
        keep=["她没接话，把秤砣放回去"],
    )
    assert report["dropped_howto"] == 1
    types = [f["type"] for f in report["flags"]]
    assert types == ["continuity_break"]
    save_editor_report(report, workspace_root=tmp_path)
    block = format_typed_editor_block(focus="ch8", workspace_root=tmp_path)
    assert "continuity_break" in block
    assert "应该" not in block
    assert "秤砣" in block


def test_editor_next_chapter_drops_info_and_caps(tmp_path: Path) -> None:
    from app.writing.editor_notes import EDITOR_NOTES_MAX_CHARS
    from app.writing.text_metrics import visible_chars

    report = normalize_editor_report(
        section_id="ch7",
        flags=[
            {
                "type": "continuity_break",
                "where": "ch7",
                "evidence": "周婶已出城",
                "severity": "hard",
            },
            {
                "type": "surface_observation",
                "where": "ch7",
                "evidence": "对白连跑 6 处",
                "severity": "info",
            },
        ]
        + [
            {
                "type": "reader_confusion",
                "where": f"ch7 段{i}",
                "evidence": "读者不知道铜铃和码头有关。" + ("证据拉长。" * 20),
                "severity": "soft",
            }
            for i in range(8)
        ],
        keep=["她没接话，把秤砣放回去——这是这本书的样子"] * 3,
    )
    save_editor_report(report, workspace_root=tmp_path)
    block = format_typed_editor_block(focus="ch8", workspace_root=tmp_path)
    assert "continuity_break" in block
    assert "surface_observation" not in block
    assert "对白连跑" not in block
    assert visible_chars(block) <= EDITOR_NOTES_MAX_CHARS


def test_editor_phase_has_no_write_tools() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    registry = build_registry()
    names = {s.name for s in tool_scope(profile, registry, editor_phase=True)}
    assert "editor_report" in names
    assert "read_file" in names
    assert "draft_section" not in names
    assert "propose_patch" not in names
    assert "update_outline" not in names


def test_editor_block_falls_back_to_regex_notes(tmp_path: Path) -> None:
    write_editor_notes("ch1", ["段落长度几乎一样。"], workspace_root=tmp_path)
    nxt = format_editor_notes_block(focus="ch2", workspace_root=tmp_path)
    assert "段落长度几乎一样" in nxt


@pytest.mark.asyncio
async def test_editor_report_handler_phase_gate(workspace: Path) -> None:
    from app.tools.core import tools as core

    denied = await core.editor_report(
        "ch7",
        flags=[{"type": "continuity_break", "where": "ch7", "evidence": "周婶已出城", "severity": "hard"}],
        turn_user_text="写第七章",
    )
    assert denied["error"] == "editor_not_in_phase"
    ok = await core.editor_report(
        "ch7",
        flags=[{"type": "continuity_break", "where": "ch7", "evidence": "周婶已出城", "severity": "hard"}],
        keep=["她没接话"],
        turn_user_text="/edit 第七章",
    )
    assert ok["status"] == "ok"
    assert (workspace / ".agent" / "work" / "editor" / "ch7.json").is_file()


def test_observations_include_l0_and_stale(tmp_path: Path) -> None:
    import json

    from app.writing.author_state import update_author_state
    from app.writing.editor import format_observations_block

    text = "这本书写的是码头上不肯回头的人，冷、慢、不解释。"
    for _ in range(3):
        update_author_state("立场", text, workspace_root=tmp_path)
    man = (
        tmp_path
        / ".agent"
        / "sessions"
        / "s1"
        / "turns"
        / "t1"
        / "manifest.json"
    )
    man.parent.mkdir(parents=True)
    man.write_text(
        json.dumps(
            {
                "section_drafts": {
                    "ch7": {"l0_hits": ["staccato_uniform"], "net_signal": -0.4}
                }
            }
        ),
        encoding="utf-8",
    )
    block = format_observations_block(workspace_root=tmp_path)
    assert "[observations]" in block
    assert "L0=" in block
    assert "author_state_stale" in block
