from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import should_index_source
from app.writing.cards import (
    build_writing_system_prompt,
    load_writing_cards,
    select_writing_cards,
)


def _seed_cards(workspace: Path) -> None:
    root = workspace / "sources" / "cards"
    (root / "characters").mkdir(parents=True)
    (root / "style").mkdir(parents=True)
    (root / "plots").mkdir(parents=True)
    (root / "characters" / "张白鹿.md").write_text(
        "---\nkind: character\ntitle: 张白鹿\n---\n"
        "性格独立，不依附李云龙。禁止写成花瓶。\n",
        encoding="utf-8",
    )
    (root / "style" / "写作风格.md").write_text(
        "---\nkind: style\n---\n"
        "多写战场间隙的人物对峙。情节节奏偏冷硬，少煽情旁白。\n",
        encoding="utf-8",
    )
    (root / "plots" / "第一章摘要.md").write_text(
        "# 第一章摘要\n雨夜进城，两人初次交锋。\n",
        encoding="utf-8",
    )


def test_load_and_select_character_card(tmp_path: Path) -> None:
    _seed_cards(tmp_path)
    cards = load_writing_cards(workspace_root=tmp_path)
    assert len(cards) == 3
    selected = select_writing_cards("写一节张白鹿人物戏", cards)
    titles = [card.title for card in selected]
    assert "张白鹿" in titles
    assert any(card.kind == "style" for card in selected)


def test_cards_excluded_from_rag_index(tmp_path: Path) -> None:
    path = tmp_path / "sources" / "cards" / "characters" / "张白鹿.md"
    assert should_index_source(path) is False
    assert should_index_source(tmp_path / "sources" / "亮剑.md") is True


def test_prepare_writing_system_prompt_event_payload(tmp_path: Path) -> None:
    _seed_cards(tmp_path)
    from app.writing.cards import prepare_writing_system_prompt

    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "按设定写张白鹿",
        workspace_root=tmp_path,
    )
    payload = pin.event_payload()
    assert payload["available_count"] == 3
    assert any(card["title"] == "张白鹿" for card in payload["cards"])
    assert "Writing cards（必须遵守）" in pin.prompt



def test_card_budget_truncates(tmp_path: Path) -> None:
    root = tmp_path / "sources" / "cards" / "characters"
    root.mkdir(parents=True)
    (root / "长卡.md").write_text("角色设定\n" + ("详细内容" * 400), encoding="utf-8")
    cards = load_writing_cards(workspace_root=tmp_path)
    selected = select_writing_cards("长卡", cards, max_chars=300, per_card_chars=200)
    assert selected
    assert len(selected[0].body) <= 200
