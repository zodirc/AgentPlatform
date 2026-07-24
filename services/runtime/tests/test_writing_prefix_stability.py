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
    h1 = stable_cards_prefix_hash(extract_cards_block(pin1.volatile_block))
    h2 = stable_cards_prefix_hash(extract_cards_block(pin2.volatile_block))
    h3 = stable_cards_prefix_hash(extract_cards_block(pin3.volatile_block))
    assert h1 == h2 == h3
    assert pin1.event_payload()["prefix_hash"] == pin2.event_payload()["prefix_hash"]
    # WN3: stable system bytes identical across chapter/message changes
    assert pin1.prompt == pin2.prompt == pin3.prompt == base


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
    block = extract_cards_block(pin.volatile_block)
    assert "写一章" not in block
    assert "step=3" not in block


def test_wn3_stable_system_excludes_volatile_and_assemble_postposes(tmp_path: Path) -> None:
    """WT5/WN3: system stays base-only; cards/surface go to post-system user message."""
    from app.context.engine import ContextEngine
    from app.engine.state import TurnState
    from uuid import uuid4

    _seed(tmp_path)
    base = "You are a writing assistant."
    pin = prepare_writing_system_prompt(base, "写第三章", workspace_root=tmp_path)
    assert pin.prompt == base
    assert "Writing cards" in pin.volatile_block
    assert "Writing cards" not in pin.prompt

    engine = ContextEngine()
    state = TurnState(
        turn_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        trace_id=uuid4(),
        scenario_id="writing",
        messages=[{"role": "user", "content": [{"type": "text", "text": "写第三章"}]}],
        max_steps=10,
    )
    assembled = engine.assemble(
        system_prompt=pin.prompt,
        state=state,
        volatile_context=pin.volatile_block,
    )
    system_text = assembled[0]["content"][0]["text"]
    assert system_text == base or system_text.startswith(base)
    assert "Writing cards" not in system_text
    assert "Work surface" not in system_text and "## Work" not in system_text.split("\n")[0]
    volatile_msgs = [
        m
        for m in assembled
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and any(
            isinstance(b, dict) and str(b.get("text", "")).startswith("[writing_context]")
            for b in m["content"]
        )
    ]
    assert volatile_msgs
    vtext = volatile_msgs[0]["content"][0]["text"]
    assert "Writing cards" in vtext
