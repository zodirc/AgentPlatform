from __future__ import annotations

from pathlib import Path

from app.writing.focus import (
    build_work_surface_block,
    infer_focus_section_id,
    wants_full_manuscript_read,
)
from app.writing.manuscript import upsert_section


def test_infer_focus_chinese_and_ch() -> None:
    available = ["ch1", "ch2", "ch3"]
    assert infer_focus_section_id("写第三章", available) == "ch3"
    assert infer_focus_section_id("继续写 ch2", available) == "ch2"
    assert infer_focus_section_id("接着写", available) == "ch3"


def test_work_surface_includes_prev_tail(tmp_path: Path) -> None:
    doc = ""
    doc = upsert_section(doc, "ch1", "AAAA" * 100)
    doc = upsert_section(doc, "ch2", "BBBB" * 50)
    drafts = tmp_path / ".agent" / "work" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")

    block = build_work_surface_block(
        "写第二章",
        workspace_root=tmp_path,
        max_chars=8000,
        prev_tail_chars=80,
        focus_max_chars=5000,
    )
    assert "focus: `ch2`" in block
    assert "Previous tail" in block or "prev_tail" in block
    assert "Focus (`ch2`)" in block


def test_work_surface_pins_outline_job(tmp_path: Path) -> None:
    doc = upsert_section("", "ch3", "本章正文。" * 20)
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    (tmp_path / "outline.md").write_text(
        "主线：沈禾要保住铺子，挡着的是粮行。\n\n"
        "# 第三章\n加压：核秤，不摊牌。\n",
        encoding="utf-8",
    )
    block = build_work_surface_block("写第三章", workspace_root=tmp_path)
    assert "Outline spine" in block
    assert "保住铺子" in block
    assert "Outline job (`ch3`)" in block
    assert "核秤" in block
    assert "假高潮" in block


def test_wants_full_manuscript_read() -> None:
    assert wants_full_manuscript_read("请通读全文检查人称", full_flag=False) is True
    assert wants_full_manuscript_read("写第三章", full_flag=False) is False
    assert wants_full_manuscript_read("", full_flag=True) is True
