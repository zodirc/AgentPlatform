from __future__ import annotations

from pathlib import Path

from app.writing.work_index import build_work_index


def test_build_work_index_lists_manuscript(tmp_path: Path) -> None:
    (tmp_path / "outline.md").write_text("# Book\n", encoding="utf-8")
    drafts = tmp_path / ".agent" / "work" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(
        "<!-- section:ch1 -->\none\n<!-- /section:ch1 -->\n",
        encoding="utf-8",
    )
    (tmp_path / "manuscript.md").write_text(
        "<!-- section:ch1 -->\none\n<!-- /section:ch1 -->\n",
        encoding="utf-8",
    )

    text = build_work_index(workspace_root=tmp_path, max_chars=2000)
    assert "## Work index" in text
    assert "monofile" in text
    assert "manuscript.md" in text
    assert "ch1" in text


def test_build_work_index_respects_budget(tmp_path: Path) -> None:
    (tmp_path / "sections").mkdir()
    for i in range(40):
        (tmp_path / "sections" / f"ch{i}.md").write_text("x", encoding="utf-8")
    text = build_work_index(workspace_root=tmp_path, max_chars=280)
    assert len(text) <= 280
