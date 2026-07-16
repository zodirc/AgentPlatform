from __future__ import annotations

from pathlib import Path

from app.writing.cards import (
    extract_cards_block,
    prepare_writing_system_prompt,
    select_writing_cards,
    stable_cards_prefix_hash,
    _truncate,
)


def _seed(workspace: Path) -> None:
    root = workspace / "sources" / "cards"
    (root / "style").mkdir(parents=True)
    (root / "characters").mkdir(parents=True)
    (root / "style" / "voice.md").write_text(
        "---\nkind: style\ntitle: Voice\n---\n"
        "## Voice\n冷硬旁白\n## Don't\n禁止排比堆砌\n",
        encoding="utf-8",
    )
    (root / "characters" / "李云龙.md").write_text(
        "---\nkind: character\ntitle: 李云龙\n---\n粗豪直率，不说空话。\n",
        encoding="utf-8",
    )


def test_c1_select_deterministic_across_messages(tmp_path: Path) -> None:
    _seed(tmp_path)
    from app.writing.cards import load_writing_cards

    cards = load_writing_cards(workspace_root=tmp_path)
    first = select_writing_cards("按资料写第三章", cards)
    second = select_writing_cards("第三段重写，弱化说教", cards)
    assert [(c.path, c.kind, c.body) for c in first] == [
        (c.path, c.kind, c.body) for c in second
    ]


def test_c2_truncate_idempotent() -> None:
    text = "abcdefghij" * 50
    a, t1 = _truncate(text, 40)
    b, t2 = _truncate(text, 40)
    assert a == b
    assert t1 is True and t2 is True
    assert _truncate(a, 40) == (a, False)


def test_c3_corridor_prefix_stable_across_passes(tmp_path: Path) -> None:
    _seed(tmp_path)
    base = "You are a writing assistant."
    pin1 = prepare_writing_system_prompt(base, "先列大纲", workspace_root=tmp_path)
    pin2 = prepare_writing_system_prompt(base, "按资料写第3章", workspace_root=tmp_path)
    pin3 = prepare_writing_system_prompt(base, "第三段重写", workspace_root=tmp_path)
    h1 = stable_cards_prefix_hash(extract_cards_block(pin1.prompt))
    h2 = stable_cards_prefix_hash(extract_cards_block(pin2.prompt))
    h3 = stable_cards_prefix_hash(extract_cards_block(pin3.prompt))
    assert h1 == h2 == h3
    assert pin1.event_payload()["prefix_hash"] == pin2.event_payload()["prefix_hash"]


def test_c4_card_edit_changes_prefix(tmp_path: Path) -> None:
    _seed(tmp_path)
    base = "You are a writing assistant."
    before = prepare_writing_system_prompt(base, "pass-a", workspace_root=tmp_path)
    hash_before = before.event_payload()["prefix_hash"]
    style = tmp_path / "sources" / "cards" / "style" / "voice.md"
    style.write_text(
        "---\nkind: style\ntitle: Voice\n---\n"
        "## Voice\n改写后的文风\n## Don't\n禁止排比堆砌\n",
        encoding="utf-8",
    )
    after = prepare_writing_system_prompt(base, "pass-a", workspace_root=tmp_path)
    hash_after = after.event_payload()["prefix_hash"]
    assert hash_before != hash_after
    # Unchanged cards → hash stable again
    again = prepare_writing_system_prompt(base, "pass-b", workspace_root=tmp_path)
    assert again.event_payload()["prefix_hash"] == hash_after


def test_c5_runtime_and_plan_not_in_cards_prefix(tmp_path: Path) -> None:
    _seed(tmp_path)
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一章 [plan_hint] step=3",
        workspace_root=tmp_path,
    )
    assert "[runtime_context]" not in pin.prompt
    assert "[plan_hint]" not in pin.prompt
    # User message content must not leak into the cards block
    block = extract_cards_block(pin.prompt)
    assert "写一章" not in block
    assert "step=3" not in block
