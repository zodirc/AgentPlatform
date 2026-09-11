from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.bootstrap import build_registry, tool_scope
from app.scenarios.registry import ScenarioRegistry
from app.writing.manuscript import upsert_section
from app.writing.reread import (
    build_reread_pack,
    format_retcon_execute_instruction,
    save_retcon_pending,
    should_gate_reread_phase,
)
from app.writing.taste import append_taste_mark


def test_reread_gate_phrases() -> None:
    assert should_gate_reread_phase("/reread")
    assert should_gate_reread_phase("[reread] 回头读")
    assert should_gate_reread_phase("回头读读这本书")
    assert not should_gate_reread_phase("续写第三章")


def test_reread_pack_has_source_labels_no_scores(tmp_path: Path) -> None:
    doc = upsert_section("", "ch1", "开篇第一句就站在码头上。" * 40)
    doc = upsert_section(doc, "ch2", "铜铃响了第三次。" * 40)
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text(doc, encoding="utf-8")
    append_taste_mark(
        section_id="ch1",
        kind="yes",
        excerpt="开篇第一句就站在码头上。",
        workspace_root=tmp_path,
    )
    append_taste_mark(
        section_id="ch2",
        kind="yes",
        excerpt="编辑觉得这段好但是用户没圈。",
        source="editor",
        workspace_root=tmp_path,
    )
    pack = build_reread_pack(workspace_root=tmp_path)
    text = str(pack.get("text") or "")
    assert "开篇第一句就站在码头上" in text
    assert "用户圈：就是这样" in text
    assert "编辑觉得这段好但是用户没圈" not in text
    assert "net_signal" not in text
    assert "penalty" not in text.lower()
    from app.writing.text_metrics import visible_chars

    assert visible_chars(text) <= 9000


def test_reread_pack_honors_opening_budget(tmp_path: Path) -> None:
    from app.writing.text_metrics import visible_chars

    doc = upsert_section("", "ch1", "甲" * 2000)
    doc = upsert_section(doc, "ch2", "乙" * 200)
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "manuscript.md").write_text(doc, encoding="utf-8")
    pack = build_reread_pack(workspace_root=tmp_path)
    text = str(pack.get("text") or "")
    first = text.split("\n\n", 1)[0]
    assert "第 1 章开头" in first
    assert visible_chars(first) <= 1200 + 20


def test_reread_phase_excludes_draft_tools() -> None:
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    registry = build_registry()
    names = {s.name for s in tool_scope(profile, registry, reread_phase=True)}
    assert "reread_book" in names
    assert "propose_retcon" in names
    assert "author_state" in names
    assert "draft_section" not in names
    assert "propose_patch" not in names


def test_retcon_execute_instruction(tmp_path: Path) -> None:
    save_retcon_pending(
        [{"ch": "ch1", "old_text": "旧句", "new_text": "新句", "why": "对不上"}],
        workspace_root=tmp_path,
    )
    text = format_retcon_execute_instruction(workspace_root=tmp_path)
    assert "propose_patch" in text
    assert "旧句" in text
    assert "不要 draft_section" in text


@pytest.mark.asyncio
async def test_reread_book_and_retcon_handlers(workspace: Path) -> None:
    from app.tools.core import tools as core
    from app.writing.manuscript import upsert_section

    blocked = await core.reread_book(turn_user_text="续写第三章")
    assert blocked["error"] == "reread_not_in_phase"
    doc = upsert_section("", "ch1", "开篇站在码头上。" * 20)
    (workspace / "drafts").mkdir()
    (workspace / "drafts" / "manuscript.md").write_text(doc, encoding="utf-8")
    pack = await core.reread_book(turn_user_text="/reread")
    assert "开篇站在码头上" in str(pack.get("text") or "")
    denied = await core.propose_retcon(
        items=[{"ch": "ch1", "old_text": "旧", "new_text": "新", "why": "对不上"}],
        turn_user_text="续写",
    )
    assert denied["error"] == "reread_not_in_phase"
    ok = await core.propose_retcon(
        items=[{"ch": "ch1", "old_text": "旧", "new_text": "新", "why": "对不上"}],
        turn_user_text="/reread",
    )
    assert ok["awaiting_consent"] is True
    blob = str(ok)
    assert ".agent" not in blob
    from app.writing.patch_budget import check_propose_patch_allowed

    skipped = check_propose_patch_allowed(
        {
            "section_drafts": {
                "ch1": {
                    "regime": "author",
                    "repair_span": {"key": "staccato_uniform", "old_text": "旧"},
                }
            }
        },
        section_id="ch1",
        old_text="旧",
        prior={"regime": "author"},
    )
    assert skipped is None
    note = await core.author_state(
        "回读记",
        "这本书写到现在更冷了。",
        turn_user_text="/reread",
    )
    assert note["status"] == "ok"
