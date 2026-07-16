from __future__ import annotations

from pathlib import Path

from app.retrieval.chunking import should_index_source
from app.writing.cards import (
    build_writing_system_prompt,
    extract_cards_block,
    load_writing_cards,
    parse_style_card_sections,
    prepare_writing_system_prompt,
    select_writing_cards,
    select_writing_cards_detailed,
    stable_cards_prefix_hash,
    style_card_template_path,
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


def test_inventory_pin_ignores_message(tmp_path: Path) -> None:
    _seed_cards(tmp_path)
    cards = load_writing_cards(workspace_root=tmp_path)
    a = select_writing_cards("写一节张白鹿人物戏", cards)
    b = select_writing_cards("完全无关的润色请求", cards)
    assert [(c.path, c.kind, c.body) for c in a] == [(c.path, c.kind, c.body) for c in b]


def test_cards_excluded_from_rag_index(tmp_path: Path) -> None:
    path = tmp_path / "sources" / "cards" / "characters" / "张白鹿.md"
    assert should_index_source(path) is False
    assert should_index_source(tmp_path / "sources" / "亮剑.md") is True


def test_prepare_writing_system_prompt_event_payload(tmp_path: Path) -> None:
    _seed_cards(tmp_path)
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "按设定写张白鹿",
        workspace_root=tmp_path,
    )
    payload = pin.event_payload()
    assert payload["available_count"] == 3
    assert any(card["title"] == "张白鹿" for card in payload["cards"])
    assert "Writing cards（必须遵守）" in pin.prompt
    assert "budget" in payload
    assert "prefix_hash" in payload
    assert all("truncated" in card for card in payload["cards"])


def test_card_budget_truncates(tmp_path: Path) -> None:
    root = tmp_path / "sources" / "cards" / "characters"
    root.mkdir(parents=True)
    (root / "长卡.md").write_text("角色设定\n" + ("详细内容" * 400), encoding="utf-8")
    cards = load_writing_cards(workspace_root=tmp_path)
    selected = select_writing_cards("长卡", cards, max_chars=300, per_card_chars=200)
    assert selected
    assert len(selected[0].body) <= 200
    assert selected[0].truncated is True


def test_kind_budget_drops_overflow(tmp_path: Path) -> None:
    root = tmp_path / "sources" / "cards" / "style"
    root.mkdir(parents=True)
    for i in range(3):
        (root / f"style_{i}.md").write_text(
            f"---\nkind: style\ntitle: S{i}\n---\n" + ("文风内容" * 40),
            encoding="utf-8",
        )
    cards = load_writing_cards(workspace_root=tmp_path)
    result = select_writing_cards_detailed(
        "",
        cards,
        style_max=120,
        per_card_chars=80,
        max_chars=2000,
    )
    assert result.cards
    assert result.dropped
    assert all(d.reason in {"kind_budget_exhausted", "budget_too_small"} for d in result.dropped)
    assert result.budget["by_kind"]["style"] == 120


def test_style_card_template_sections() -> None:
    path = style_card_template_path()
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "kind: style" in text
    from app.writing.cards import _parse_frontmatter

    meta, body = _parse_frontmatter(text)
    assert meta.get("kind") == "style"
    sections = parse_style_card_sections(body)
    for key in ("Voice", "Do", "Don't", "Samples", "Format"):
        assert key in sections
        assert sections[key].strip()


def test_import_samples_from_chapter() -> None:
    from app.writing.cards import import_samples_into_style_body

    chapter = (
        "# 第一章\n\n"
        "雨夜进城，李云龙站在巷口抽烟。\n\n"
        "张白鹿没有回头，只丢下一句「别跟着」。\n\n"
        "## 小节\n\n太短\n"
    )
    style_body = (
        "## Voice\nv\n\n## Do\nd\n\n## Don't\nx\n\n## Samples\nold\n\n## Format\nf\n"
    )
    merged = import_samples_into_style_body(style_body, chapter, max_paragraphs=2)
    sections = parse_style_card_sections(merged)
    assert "李云龙" in sections["Samples"]
    assert "张白鹿" in sections["Samples"]


def test_dont_enabled_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "sources" / "cards" / "style"
    root.mkdir(parents=True)
    (root / "voice.md").write_text(
        "---\nkind: style\ndont_enabled: false\n---\n"
        "## Voice\n冷\n\n## Don't\n禁止排比\n\n## Samples\ns\n",
        encoding="utf-8",
    )
    cards = load_writing_cards(workspace_root=tmp_path)
    assert cards
    assert "已关闭" in cards[0].body
