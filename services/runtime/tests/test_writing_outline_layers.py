"""分层大纲：旧文件可读，新 documents 一次提交，立意只 shadow。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.writing import outline_store
from app.writing.canon import load_canon, record_chapter_outcomes
from app.writing.outline_checks import plan_issues, prose_shadow_issues
from app.writing.premise_gate import intent_codes_from_payload, shadow_only
from app.writing.subject_pool import select_seeds
from app.writing.turn_phase import has_chapter_jobs, snapshot
from app.writing.work_reconstruction import parse_card
from app.writing.writing_pack import compile_writing_pack_parts

_REPO = Path(__file__).resolve().parents[3]


def test_premise_fixture_keeps_huishui_as_a_failure_label() -> None:
    raw = json.loads(
        (_REPO / "eval/writing_outline/premise_cases.json").read_text(encoding="utf-8")
    )
    by_id = {row["id"]: row for row in raw}
    assert by_id["huishui-lane"]["expect_codes"] == ["noun_graft"]
    allowed = {
        "no_human_pull",
        "genre_decorative",
        "noun_graft",
        "moral_pre_solved",
        "no_serial_engine",
    }
    assert {
        "broad-genre",
        "named-desire",
        "huishui-lane",
        "facility-first",
        "genre-wrapper",
        "genre-promise-success",
        "user-wants-trope",
        "want-others",
        "delivery-cultivation",
        "secret-office",
        "precision-as-texture",
        "registry-cultivation",
        "family-erasure-formula",
        "generic-hidden-city-tour",
        "generic-retired-master",
        "overplotted-memory-bargain",
        "forced-garden-dilemma",
    } <= set(by_id)
    assert all(set(row.get("expect_codes") or ()) <= allowed for row in raw)
    assert by_id["generic-hidden-city-tour"]["expect_selection"] == "reject"
    assert by_id["generic-retired-master"]["expect_selection"] == "reject"
    assert by_id["overplotted-memory-bargain"]["expect_selection"] == "reject"
    assert by_id["forced-garden-dilemma"]["expect_selection"] == "reject"
    assert intent_codes_from_payload({"title": "回水巷"}) == []


def test_intent_shadow_keeps_the_card() -> None:
    card = parse_card(
        json.dumps(
            {
                "title": "回水巷",
                "pitch": "管网灵气修真。" * 12,
                "intent": {"noun_graft": True, "no_human_pull": False},
            },
            ensure_ascii=False,
        )
    )
    assert card is not None
    assert card["title"] == "回水巷"
    assert shadow_only(["noun_graft", "format"]) == ["noun_graft"]


def test_reference_pool_stays_closed() -> None:
    assert select_seeds("写一篇长篇都市修真小说", 2) == []


@pytest.mark.asyncio
async def test_legacy_outline_still_reads_as_one_file(workspace: Path) -> None:
    from app.tools.core import writing_tools as core

    body = "## 这本书\n\n边荒少年要活下去。\n\n## 第1章 钟表铺\n\n" + ("他去铺子领粮。" * 8)
    written = await core.update_outline(
        body,
        turn_user_text="采用此开篇「钟表铺」",
    )
    assert written.get("status") != "error"
    assert written.get("awaiting_direction") is True
    assert outline_store.layout_of(workspace) == "legacy"
    assert outline_store.project_outline(workspace) == (workspace / "outline.md").read_text(
        encoding="utf-8"
    )
    snap = snapshot("采用此开篇「钟表铺」", workspace_root=workspace)
    assert snap["has_chapter_jobs"] is True
    assert snap["outline_ready_wait"] is True


@pytest.mark.asyncio
async def test_documents_commit_is_atomic_and_visible(workspace: Path) -> None:
    from app.tools.core import writing_tools as core

    chapter = (
        "他今晚必须把柜台的账对上，因为铺子明天开不了门。"
        "他可以选择瞒下一笔，或把亏空摊给合伙人。"
    )
    written = await core.update_outline(
        documents=[
            {
                "scope": "work",
                "content": "## 核心处境\n\n他要保住铺子。\n\n## 叙事承诺\n\n每章一个付得出的选择。\n",
            },
            {
                "scope": "volume",
                "volume_index": 1,
                "content": "## 卷问题\n\n谁来付这笔账？\n",
            },
            {"scope": "chapter", "section_id": "ch1", "content": chapter},
        ],
        turn_user_text="采用此开篇「北岸」",
    )
    assert written.get("status") != "error"
    assert written.get("awaiting_direction") is True
    assert written["changed_files"][2]["path"] == "chapters/ch-001.md"
    assert (workspace / "chapters" / "ch-001.md").read_text(encoding="utf-8").startswith("# ch1")
    from app.writing.book import load_writing_book

    kinds = {part["kind"] for part in load_writing_book(workspace_root=workspace)["parts"]}
    assert {"outline", "volume", "chapter"} <= kinds
    projected = outline_store.project_outline(workspace)
    assert has_chapter_jobs(projected) is True
    assert snapshot("采用此开篇「北岸」", workspace_root=workspace)["outline_wait"] is False
    refused = await core.update_outline(
        documents=[{"scope": "aside", "content": "x"}],
        turn_user_text="采用此开篇「北岸」",
    )
    assert refused["error"] == "bad_scope"
    assert (workspace / "chapters" / "ch-001.md").exists()


def test_outcome_needs_evidence_and_pack_drops_pitch(workspace: Path) -> None:
    prose = "天亮前他把亏空摊在柜台上，合伙人没有接。"
    recorded = record_chapter_outcomes(
        "ch1",
        prose,
        [
            {"text": "亏空摊开了", "evidence": "他把亏空摊在柜台上", "constrains_next": True},
            {"text": "他赢了", "evidence": "并不存在的句子"},
        ],
        workspace_root=workspace,
    )
    assert recorded["accepted"] == ["亏空摊开了"]
    assert recorded["rejected"]
    facts = load_canon(workspace_root=workspace)["facts"]
    assert {row["kind"] for row in facts} == {"outcome"}
    assert facts[0]["certainty"] == "confirmed"
    (workspace / "outline.md").write_text(
        "## 这本书\n\n《北岸》简介不该进写作包。\n\n## 核心处境\n\n他要保住铺子。\n\n## 叙事承诺\n\n每章一个付得出的选择。\n",
        encoding="utf-8",
    )
    (workspace / "volumes").mkdir()
    (workspace / "volumes" / "volume-001.md").write_text(
        "## 卷问题\n\n谁来付这笔账？\n",
        encoding="utf-8",
    )
    marker = workspace / ".agent" / "work" / "outline_layout"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("split\n", encoding="utf-8")
    (workspace / "chapters").mkdir()
    (workspace / "chapters" / "ch-002.md").write_text(
        "# ch2\n\n他要面对合伙人，因为亏空已经摊开。他必须选择认还是瞒。\n",
        encoding="utf-8",
    )
    (workspace / "chapters" / "ch-003.md").write_text(
        "# ch3\n\n依赖：上一章已经把亏空摊开。\n",
        encoding="utf-8",
    )
    pack = "\n".join(compile_writing_pack_parts("ch2", workspace_root=workspace))
    assert "他要保住铺子" in pack
    assert "谁来付这笔账" in pack
    assert "亏空摊开了" in pack
    assert "上一章已经把亏空摊开" in pack
    assert "简介不该进写作包" not in pack
    assert plan_issues(chapter="他走了。", volume="没有问题句", user_wants_toc=False)
    assert prose_shadow_issues("他终于意识到自己错了。")


def test_chapter_files_stay_invisible_until_split(workspace: Path) -> None:
    (workspace / "chapters").mkdir()
    (workspace / "chapters" / "ch-001.md").write_text(
        "# ch1\n\n他今晚必须把账对上，因为铺子明天开不了门。\n",
        encoding="utf-8",
    )
    assert has_chapter_jobs(outline_store.project_outline(workspace)) is False
    marker = workspace / ".agent" / "work" / "outline_layout"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("split\n", encoding="utf-8")
    assert has_chapter_jobs(outline_store.project_outline(workspace)) is True


def test_first_layered_update_lazily_migrates_legacy_chapters(workspace: Path) -> None:
    (workspace / "outline.md").write_text(
        "## 核心处境\n\n他欠着一条命。\n\n"
        "## 第1章 雨夜\n\n他今晚必须作出选择，因为两个人都在等他。\n\n"
        "## 第2章 回门\n\n第一章的选择已经改变了谁能进门。\n",
        encoding="utf-8",
    )
    result = outline_store.commit_documents(
        [{"scope": "volume", "volume_index": 1, "content": "## 卷问题\n\n谁替谁活？"}],
        workspace_root=workspace,
    )
    assert result["status"] == "ok"
    assert "第1章" not in (workspace / "outline.md").read_text(encoding="utf-8")
    assert "雨夜" in (workspace / "chapters" / "ch-001.md").read_text(encoding="utf-8")
    assert "回门" in (workspace / "chapters" / "ch-002.md").read_text(encoding="utf-8")
    assert {row["path"] for row in result["changed_files"]} == {
        "outline.md",
        "volumes/volume-001.md",
        "chapters/ch-001.md",
        "chapters/ch-002.md",
    }
    assert has_chapter_jobs(outline_store.project_outline(workspace)) is True


def test_shrink_guard_is_per_file(workspace: Path) -> None:
    (workspace / "chapters").mkdir()
    original = "账" * 600
    (workspace / "chapters" / "ch-001.md").write_text(original, encoding="utf-8")
    refused = outline_store.commit_documents(
        [{"scope": "chapter", "section_id": "ch1", "content": "太短"}],
        workspace_root=workspace,
    )
    assert refused["error"] == "outline_shrink"
    assert (workspace / "chapters" / "ch-001.md").read_text(encoding="utf-8") == original
    assert outline_store.layout_of(workspace) == "legacy"


def test_later_file_failure_restores_earlier_files(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (workspace / "outline.md").write_text("keep\n", encoding="utf-8")
    real = Path.write_text

    def fail_final_chapter(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name.startswith("ch-") and "outline_stage" not in self.parts:
            raise OSError("disk")
        return real(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_final_chapter)
    refused = outline_store.commit_documents(
        [
            {"scope": "work", "content": "## 核心处境\n\n新作品纲。\n"},
            {"scope": "volume", "volume_index": 1, "content": "## 卷问题\n\n谁付账？\n"},
            {"scope": "chapter", "section_id": "ch1", "content": "他必须选择。"},
        ],
        workspace_root=workspace,
    )
    assert refused["error"] == "outline_write_failed"
    assert (workspace / "outline.md").read_text(encoding="utf-8") == "keep\n"
    assert not (workspace / "volumes" / "volume-001.md").exists()
    assert outline_store.layout_of(workspace) == "legacy"


def test_outcome_without_next_constraint_stays_a_clue(workspace: Path) -> None:
    prose = "他把亏空摊在柜台上。"
    record_chapter_outcomes(
        "ch1",
        prose,
        [{"text": "亏空看见了", "evidence": "他把亏空摊在柜台上", "constrains_next": False}],
        workspace_root=workspace,
    )
    fact = load_canon(workspace_root=workspace)["facts"][0]
    assert fact["certainty"] == "clue"
    from app.writing.canon import previous_outcomes

    assert previous_outcomes("ch2", workspace_root=workspace) == ""


def test_outline_updated_keeps_changed_files() -> None:
    from app.contracts.event_validation import validate_event_payload
    from app.engine.agent_engine import _domain_event_payload

    payload = _domain_event_payload(
        "outline.updated",
        {
            "path": "outline.md",
            "content": "核心处境",
            "summary": "Outline updated",
            "mode": "replace",
            "changed_files": [
                {"path": "outline.md", "scope": "work"},
                {"path": "volumes/volume-001.md", "scope": "volume", "volume_index": 1},
                {"path": "chapters/ch-001.md", "scope": "chapter", "section_id": "ch1"},
            ],
        },
    )
    assert payload is not None
    assert payload["changed_files"][2]["section_id"] == "ch1"
    validate_event_payload("outline.updated", payload)
    legacy = _domain_event_payload(
        "outline.updated",
        {"path": "outline.md", "content": "旧纲", "summary": "ok", "mode": "replace"},
    )
    assert legacy is not None
    assert "changed_files" not in legacy
    validate_event_payload("outline.updated", legacy)
