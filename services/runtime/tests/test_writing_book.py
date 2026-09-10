from __future__ import annotations

import json
from pathlib import Path

from app.writing.book import discard_writing_book, load_writing_book


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_writing_book_lists_hidden_beats_and_pending_cards(workspace: Path) -> None:
    _write(workspace / "outline.md", "# 第一卷：城市暗面\n\n- 跟着谁：沈砚\n")
    _write(workspace / "drafts" / "manuscript.md", "# 第一章\n\n沈砚下了井。\n")
    _write(
        workspace / "sources" / "cards" / "pending" / "20260903T100815Z_c64072db-5852-4c1a-827f-d4e1b6f1e763_沈砚.md",
        "---\nkind: character\ntitle: 沈砚\n---\n外包电工。\n",
    )
    _write(
        workspace / ".agent" / "work" / "local_beats.json",
        json.dumps(
            {
                "beats": [
                    {
                        "fragment": "dialogue_dyad",
                        "section_id": "ch1",
                        "text": "沈砚屏住呼吸。\n\n他看见了电。" + "灯" * 80,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    _write(workspace / "sources" / "seed" / "writing" / "keep.md", "范文不动")
    _write(workspace / "sources" / "mine.md", "资料库上传")
    _write(workspace / "writing_prefs.json", '{"work_mode":"web_serial"}')

    book = load_writing_book(workspace_root=workspace)
    assert book["empty"] is False
    assert book["title"] == "第一卷：城市暗面"
    labels = [p["label"] for p in book["parts"]]
    assert "大纲" in labels
    assert "正文" in labels
    assert any(p["label"].startswith("人物 · 沈砚") for p in book["parts"])
    assert any(p["kind"] == "beat" and p["label"] == "对白" for p in book["parts"])
    blob = json.dumps(book, ensure_ascii=False)
    assert ".agent" not in blob
    assert "local_beats" not in blob
    by_key = {p["key"]: p for p in book["parts"]}
    assert by_key["outline"]["path"] == "outline.md"
    assert by_key["manuscript"]["path"] == "drafts/manuscript.md"
    people = [p for p in book["parts"] if p["kind"] == "character"]
    assert people and people[0]["path"].startswith("sources/cards/")


def test_discard_writing_book_clears_sidecar_keeps_library(workspace: Path) -> None:
    _write(workspace / "outline.md", "# 旧书\n")
    _write(workspace / "drafts" / "manuscript.md", "正文若干字。" * 20)
    _write(workspace / "drafts" / "archive" / "old.md", "# 归档\n")
    _write(
        workspace / "sources" / "cards" / "pending" / "x_沈砚.md",
        "---\nkind: character\n---\n沈砚\n",
    )
    _write(
        workspace / ".agent" / "work" / "local_beats.json",
        json.dumps({"beats": [{"fragment": "mixed", "text": "拍" * 90}]}),
    )
    _write(workspace / ".agent" / "work" / "history" / "ch1" / "a.md", "旧快照")
    _write(workspace / "writing" / "style.lock", "theme: x\n")
    _write(workspace / "sources" / "seed" / "writing" / "keep.md", "范文")
    _write(workspace / "sources" / "mine.md", "资料")
    _write(workspace / "writing_prefs.json", '{"work_mode":"web_serial"}')
    _write(
        workspace / ".agent" / "work" / "story_state.json",
        '{"pressures":[],"info_gaps":[],"wild_cards":[7]}',
    )
    _write(workspace / ".agent" / "work" / "story_state.md", "# 账本\n")
    _write(workspace / ".agent" / "work" / "author_notes.md", "## ch1\n疑心\n")
    _write(workspace / ".agent" / "work" / "editor_notes" / "ch1.md", "- 短句\n")
    _write(workspace / ".agent" / "work" / "surface" / "ch1.json", "{}")
    _write(workspace / ".agent" / "work" / "surface_index.json", '{"chapters":[]}')

    result = discard_writing_book(workspace_root=workspace)
    assert result["ok"] is True
    book = result["book"]
    assert book["empty"] is True
    assert book["title"] == "还没有书"
    assert not (workspace / "outline.md").exists()
    assert not (workspace / "drafts" / "manuscript.md").exists()
    assert not (workspace / ".agent" / "work" / "local_beats.json").exists()
    assert not (workspace / "writing" / "style.lock").exists()
    pending = list((workspace / "sources" / "cards").rglob("*.md"))
    assert pending == []
    assert (workspace / "sources" / "seed" / "writing" / "keep.md").read_text(
        encoding="utf-8"
    ) == "范文"
    assert (workspace / "sources" / "mine.md").read_text(encoding="utf-8") == "资料"
    assert not (workspace / ".agent" / "work" / "story_state.json").exists()
    assert not (workspace / ".agent" / "work" / "story_state.md").exists()
    assert not (workspace / ".agent" / "work" / "author_notes.md").exists()
    assert '"work_mode":"web_serial"' in (workspace / "writing_prefs.json").read_text(
        encoding="utf-8"
    )


def test_empty_workspace_is_empty_book(workspace: Path) -> None:
    book = load_writing_book(workspace_root=workspace)
    assert book["empty"] is True
    assert book["parts"] == []
