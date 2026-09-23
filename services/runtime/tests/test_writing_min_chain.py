"""最小主链回归：普通写章不走规划、盲审和修订。"""

from __future__ import annotations

from pathlib import Path

from app.scenarios.registry import ScenarioRegistry
from app.tools.bootstrap import REVISION_PHASE_TOOL_ALLOWLIST, build_registry, tool_scope
from app.writing.canon import chapter_candidates, format_active_facts, record_fact
from app.writing.editor import format_observations_block, normalize_editor_report
from app.writing.focus import build_work_surface_block
from app.writing.manuscript import upsert_section
from app.writing.reread import should_gate_editor_phase
from app.writing.revision import (
    build_revision_context,
    concrete_revision_request,
    should_apply_revision,
    should_gate_revision_phase,
)
from app.writing.subtype import serial_subtype_block
from app.writing.chain_boundary import REVISION_REQUEST_FIELDS, WRITER_HIDES
from app.writing.taste import append_taste_mark, format_taste_block, format_voice_offer, load_voice_choice
from app.writing.text_metrics import draft_length_fields


def test_default_writer_omits_control_plane(tmp_path: Path) -> None:
    doc = upsert_section("", "ch1", "她把秤砣放回柜台。" * 20)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    (tmp_path / "outline.md").write_text(
        "## 这本书\n人物成长与秩序。\n\n"
        "## 当前阶段\n阶段变化：责任压上来。\n\n"
        "## 第一章\n当前章段：陆沉舟在柜台前核秤。母亲不肯让他把心相取走。\n",
        encoding="utf-8",
    )
    block = build_work_surface_block("写第一章", workspace_root=tmp_path, max_chars=8000)
    assert "### 写作包" in block
    assert "核秤" in block
    assert "人物成长" not in block
    assert "阶段变化" not in block
    assert "子类型" not in block
    assert "Narrative commitment" not in block
    assert "repair" not in block.lower()
    assert serial_subtype_block("写一部凡人流长篇", "稳健宗门") == ""


def test_writing_pack_allows_gaps(tmp_path: Path) -> None:
    block = build_work_surface_block("写第一章", workspace_root=tmp_path, max_chars=4000)
    assert "不要补目标、期限或冲突" in block
    assert "期限：" not in block
    assert "冲突：" not in block


def test_ordinary_chapter_does_not_open_side_phases() -> None:
    message = "写第一章"
    assert should_gate_editor_phase(message) is False
    assert should_gate_revision_phase(message) is False
    assert should_apply_revision(message) is False


def test_canon_splits_confirmed_and_clues(tmp_path: Path) -> None:
    prose = "老钟落水死了。周婶说：「他还活着。」也许门后有人。他暂时把秤留在柜上。"
    rows = chapter_candidates("ch1", prose)
    kinds = {row["kind"] for row in rows}
    assert "change" not in kinds
    assert "character" in kinds
    assert "speech" in kinds
    assert "guess" in kinds
    assert "state" in kinds
    record_fact(
        kind="character",
        text="老钟已死",
        source_section="ch1",
        evidence="老钟落水死了。",
        subject="老钟",
        certainty="confirmed",
        workspace_root=tmp_path,
    )
    record_fact(
        kind="speech",
        text="周婶说他还活着",
        source_section="ch1",
        evidence="周婶说：「他还活着。」",
        subject="周婶",
        workspace_root=tmp_path,
    )
    shown = format_active_facts(focus="ch2", workspace_root=tmp_path, query="老钟")
    assert "老钟已死" in shown
    assert "原文：" in shown
    assert "周婶" not in shown


def test_state_update_is_timeline_not_conflict(tmp_path: Path) -> None:
    first = record_fact(
        kind="character",
        text="老钟已离开",
        source_section="ch1",
        evidence="老钟出城。",
        subject="老钟",
        workspace_root=tmp_path,
    )
    second = record_fact(
        kind="character",
        text="老钟已死",
        source_section="ch3",
        evidence="老钟落水死了。",
        subject="老钟",
        workspace_root=tmp_path,
    )
    assert first == "active"
    assert second == "updated"


def test_unconfirmed_draft_does_not_become_voice(tmp_path: Path) -> None:
    append_taste_mark(
        section_id="ch1",
        kind="yes",
        excerpt="她没接话，把秤砣放回去。",
        source="editor",
        workspace_root=tmp_path,
    )
    block = format_taste_block(workspace_root=tmp_path)
    assert "编辑保留，用户未反对" in block
    append_taste_mark(
        section_id="ch1",
        kind="off",
        excerpt="她没接话，把秤砣放回去。",
        workspace_root=tmp_path,
    )
    revoked = format_taste_block(workspace_root=tmp_path)
    assert "她没接话" not in revoked


def test_editor_first_pass_hides_detectors_and_allows_zero(tmp_path: Path) -> None:
    block = format_observations_block(workspace_root=tmp_path)
    assert "L0=" not in block
    assert "staccato_uniform" not in block
    report = normalize_editor_report(section_id="ch1", flags=[], keep=[])
    assert report["flags"] == []


def test_revision_does_not_write_until_choice() -> None:
    vague = "去掉AI味"
    assert should_gate_revision_phase(vague) is True
    assert concrete_revision_request(vague) is False
    text = build_revision_context(vague)
    assert "这句不够" in text
    assert "propose_patch" not in REVISION_PHASE_TOOL_ALLOWLIST
    assert "draft_section" not in REVISION_PHASE_TOOL_ALLOWLIST
    ScenarioRegistry.load()
    profile = ScenarioRegistry.get("writing")
    names = {
        spec.name
        for spec in tool_scope(
            profile, build_registry(), revision_phase=True, editor_phase=True
        )
    }
    assert "propose_patch" not in names
    assert "draft_section" not in names
    assert "stub_echo" not in names
    assert should_apply_revision("采用候选 A") is True
    assert should_gate_revision_phase("采用候选 A") is False


def test_opening_voice_candidates_are_not_auto_saved(tmp_path: Path) -> None:
    block = format_voice_offer("写第一章", workspace_root=tmp_path)
    assert "声口候选" in block
    assert "A." in block and "B." in block
    assert load_voice_choice(workspace_root=tmp_path) == ""
    chosen = format_voice_offer("声口用 A", workspace_root=tmp_path)
    assert "用户选定" in chosen
    assert load_voice_choice(workspace_root=tmp_path) == "A"
    assert "commitment" in WRITER_HIDES
    assert "problem" in REVISION_REQUEST_FIELDS


def test_short_chapter_is_explicit_exception() -> None:
    fields = draft_length_fields("短。" * 10, "这一章是短章")
    assert fields.get("length_exception") == "short_chapter"
    assert "length_short" not in fields
