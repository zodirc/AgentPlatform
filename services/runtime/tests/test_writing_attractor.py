"""Cold-start priors must not default the shop / ferry attractor."""

from __future__ import annotations

from pathlib import Path

from app.writing.cards import (
    default_voice_card_path,
    parse_style_card_sections,
    prepare_writing_system_prompt,
    _parse_frontmatter,
)
from app.writing.signals.spec import build_writing_spec_block

# Detection exemplars stay in the score bank; they must not leak into the
# empty-window prior (spec + default voice) for a bare 「写一篇故事」.
_SHOP_ATTRACTORS = (
    "格局",
    "柜台",
    "温酒",
    "鲁镇的酒店",
    "鲁镇酒店",
    "曲尺形",
)
_FERRY_ATTRACTORS = ("灵灯", "水路渡口", "查父失踪")


def _hits(text: str) -> list[str]:
    return [tok for tok in (*_SHOP_ATTRACTORS, *_FERRY_ATTRACTORS) if tok in (text or "")]


def test_default_voice_samples_are_not_the_shop_counter() -> None:
    _meta, body = _parse_frontmatter(
        default_voice_card_path().read_text(encoding="utf-8")
    )
    samples = parse_style_card_sections(body).get("Samples") or ""
    assert "孔乙己" in samples
    assert _hits(samples) == []


def test_cold_start_spec_plus_voice_skips_shop_attractor(tmp_path: Path, monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写一篇故事", workspace_root=tmp_path)
    assert "fragment: `mixed`" in spec
    assert "worldview_texture" not in spec
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一篇故事",
        workspace_root=tmp_path,
    )
    prior = f"{spec}\n{pin.volatile_block}"
    assert _hits(prior) == []
    assert "特务踹门" not in prior


def test_long_opening_without_outline_spec_is_mixed_not_texture() -> None:
    spec = build_writing_spec_block("写一章长篇玄幻小说里的第一章")
    assert "fragment: `mixed`" in spec
    assert "worldview_texture" not in spec
    assert _hits(spec) == []
    assert "另起人与事" in spec
    assert "不是换皮" not in spec
    assert "沈砚" not in spec
    assert "看见代价" not in spec


def test_standing_priors_do_not_force_same_book_under_new_coat() -> None:
    from app.writing.outline_arc import STYLE_CONTRACT_OUTLINE_TEMPLATE

    root = Path(__file__).resolve().parents[1] / "app" / "scenarios" / "writing"
    system = (root / "system.md").read_text(encoding="utf-8")
    voice = (root / "templates" / "web_serial_voice.md").read_text(encoding="utf-8")
    assert "新信息、新对手、新代价、新抉择" not in system
    assert "看见代价" not in system
    assert "由谁承担" not in system
    assert "另一本书" in system
    assert "不是换皮" not in system
    assert "直说" in system
    assert "读者追悬念、冲突、信息差、变强台阶" not in voice
    assert "换声口" in voice
    assert "看见代价" not in voice
    assert "这本在写谁" in STYLE_CONTRACT_OUTLINE_TEMPLATE
    assert "沈砚" not in STYLE_CONTRACT_OUTLINE_TEMPLATE
    assert "查父失踪" not in system
    assert "水路渡口+灵灯" not in system


def test_committed_style_spec_does_not_ask_to_reinvent_the_book(
    tmp_path: Path, monkeypatch
) -> None:
    from app.settings import settings
    from app.writing.outline_phase import write_style_lock

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    outline = (
        "## 风格契约\n\n**路数**：探案仙侠\n\n"
        "**世界怎么运转**：衙门、税册、案卷织网；超凡要查得证。\n\n"
        "**文字与节奏**：市井气，一案一结。\n\n"
        "**开篇质地**：第一场要具体可验。\n\n"
        "**边界**：推理不靠降神。\n\n"
        "**这本在写谁**：韩校尉\n\n"
        "**这本在写什么**：井下那张帖要验得住。\n"
    )
    (tmp_path / "outline.md").write_text(outline + "x" * 80, encoding="utf-8")
    write_style_lock(outline, workspace_root=tmp_path)
    spec = build_writing_spec_block(
        "写一章长篇玄幻小说里的第一章",
        workspace_root=tmp_path,
    )
    assert "另起人与事" not in spec
