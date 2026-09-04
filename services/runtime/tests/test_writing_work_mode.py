from __future__ import annotations

from pathlib import Path

import pytest

from app.writing.signals.spec import build_writing_spec_block, infer_fragment_from_duty
from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.work_mode import (
    default_opening_duty,
    element_obligation,
    fragment_obligations,
    infer_chapter_element,
    infer_work_mode,
)


def test_infer_work_mode_web_serial() -> None:
    assert infer_work_mode("写一章长篇修仙小说的第一章") == "web_serial"
    assert infer_work_mode("玄幻网文，主角升级") == "web_serial"


def test_infer_work_mode_literary() -> None:
    assert infer_work_mode("仿鲁迅写一篇短篇小说") == "literary"
    assert infer_work_mode("写一篇故事") == "literary"


def test_infer_work_mode_genre_outranks_short_form() -> None:
    assert infer_work_mode("写一篇玄幻短篇") == "web_serial"
    assert infer_work_mode("修仙短篇") == "web_serial"


def test_infer_chapter_element() -> None:
    assert infer_chapter_element("本章主写人物关系与对白") == "character"
    assert infer_chapter_element("情节推进：发现线索") == "plot"
    assert infer_chapter_element("环境：写镇口规矩") == "environment"


def test_infer_fragment_from_duty_three_elements() -> None:
    assert infer_fragment_from_duty("人物：写贺停舟与掌柜") == "dialogue_dyad"
    assert infer_fragment_from_duty("环境：写界碑与规矩") == "worldview_texture"
    assert infer_fragment_from_duty("情节：追索失踪的修士") == "plot_progress"


def test_default_opening_duty_differs_by_mode() -> None:
    lit = default_opening_duty("literary")
    web = default_opening_duty("web_serial")
    assert "机构" in lit or "可先站" in lit
    assert "得到" in web or "发现" in web
    assert "前三分之一" in web or "功法" in web
    assert "ch2" not in web and "ch3" not in web
    hook = default_opening_duty("web_serial", chapter_kind="conflict_hook")
    assert "强钩" in hook or "麻烦" in hook
    urban = default_opening_duty(
        "web_serial",
        message="写一章长篇修真小说的第一章, 现代都市题材，我看看",
    )
    assert "发觉" in urban
    assert "有人的日子" in urban
    assert "灵视" not in urban
    occult = default_opening_duty(
        "web_serial",
        message="写一章都市灵异修真",
    )
    assert "灵视" in occult or "异象" in occult
    for blob in (lit, web, hook, urban, occult):
        assert "禁止" not in blob
        assert "勿" not in blob
        assert "不要" not in blob


def test_spec_block_opening_live_character(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写一章长篇玄幻小说里的第一章")
    assert "work_mode: `web_serial`" in spec
    assert "book_scope: `long`" in spec
    assert "开篇" in spec
    assert "评分切片" in spec
    assert "world_rule" not in spec
    assert "live_character" not in spec
    assert "过日子—加压—落下" not in spec
    assert "一两句" in spec
    assert "勿" not in spec


def test_spec_block_single_story(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写一篇故事")
    assert "book_scope: `single`" in spec
    assert "单篇" in spec
    assert "开篇窗口" not in spec
    assert "勿" not in spec


def test_spec_block_literary_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写一篇故事")
    assert "work_mode: `literary`" in spec


def test_resolve_work_mode_user_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings
    from app.writing.work_mode import resolve_work_mode, save_work_mode_override

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_work_mode_override(mode="web_serial", source="user", workspace_root=tmp_path)
    mode, source = resolve_work_mode("写一篇故事", workspace_root=tmp_path)
    assert mode == "web_serial"
    assert source == "user"


def test_resolve_work_mode_auto_ignores_stored_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import settings
    from app.writing.work_mode import resolve_work_mode, save_work_mode_override

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_work_mode_override(mode="web_serial", source="auto", workspace_root=tmp_path)
    mode, source = resolve_work_mode("写一篇故事", workspace_root=tmp_path)
    assert mode == "literary"
    assert source == "auto"


def test_spec_block_respects_user_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings
    from app.writing.work_mode import save_work_mode_override

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_work_mode_override(mode="web_serial", source="user", workspace_root=tmp_path)
    spec = build_writing_spec_block("写一篇故事")
    assert "work_mode: `web_serial`" in spec
    assert "手动" in spec


def test_platform_weights_differ_by_mode() -> None:
    wp = _writing_prefs()
    lit = wp.platform_fragment_weights("literary")["plot_progress"]
    web = wp.platform_fragment_weights("web_serial")["plot_progress"]
    assert web["pacing"] > lit["pacing"]
    assert web["structure"] > lit["structure"]


def test_apply_work_mode_overlay() -> None:
    wp = _writing_prefs()
    base = wp.platform_prefs_payload(work_mode="literary")
    web = wp.apply_work_mode_overlay(base, "web_serial")
    assert web["work_mode"] == "web_serial"
    pen = web["signal_penalties"]["mixed"]["serial_hook_flat"]
    assert pen < 0


def test_fragment_obligations_are_statements() -> None:
    banned = ("禁止", "勿", "不要")
    for mode in ("literary", "web_serial"):
        blob = "\n".join(fragment_obligations(mode).values())
        for tok in banned:
            assert tok not in blob, (mode, tok)
        for element in ("character", "plot", "environment"):
            line = element_obligation(element, mode)
            for tok in banned:
                assert tok not in line, (mode, element, tok)


def test_default_style_gains_not_full() -> None:
    wp = _writing_prefs()
    lit = wp.default_style_gains("literary")
    web = wp.default_style_gains("web_serial")
    assert max(lit.values()) < 1.0
    assert max(web.values()) < 1.0
    assert lit["dialogue_dyad"] > lit["battle_action"]
    assert web["plot_progress"] > web["dialogue_dyad"]
    prefs = wp.platform_prefs_payload(work_mode="literary")
    assert prefs["style_gains"]["dialogue_dyad"] == lit["dialogue_dyad"]
    # Scaled: not full platform delta
    full = wp.PLATFORM_SIGNAL_PENALTIES["staccato_uniform"]
    scaled = prefs["signal_penalties"]["dialogue_dyad"]["staccato_uniform"]
    assert abs(scaled - full * lit["dialogue_dyad"]) < 1e-6


def test_style_gains_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings
    from app.writing.work_mode import (
        load_style_gains,
        save_style_gains,
        writing_prefs_path,
    )

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    save_style_gains({"dialogue_dyad": 0.4, "mixed": 0.9}, workspace_root=tmp_path)
    assert writing_prefs_path(workspace_root=tmp_path).is_file()
    gains = load_style_gains(work_mode="literary", workspace_root=tmp_path)
    assert gains["dialogue_dyad"] == 0.4
    assert gains["mixed"] == 0.9
    # Missing keys filled from literary defaults
    assert 0 < gains["battle_action"] < 1


def test_serial_hook_flat_allows_immersed_cultivation() -> None:
    from app.writing.signals.prose import serial_hook_flat
    from app.writing.text_metrics import visible_chars

    body = (
        "外门杂役院的晨钟响了。周野把木桶提到井边，井水上漂着一层薄薄的灵气，像油花。"
        "师兄说过，能看见这层气的人，才配去领入门功法。他已经看了三个月。"
        "今天井壁上那道淡青的纹终于清楚了，像有人用指甲划过石头。"
    )
    text = (body + "\n\n") * 6
    assert visible_chars(text) >= 400
    assert serial_hook_flat(text, "ch1") is False


def test_serial_hook_flat_allows_self_discovery() -> None:
    from app.writing.signals.prose import serial_hook_flat
    from app.writing.text_metrics import visible_chars

    body = (
        "周野把电动车停在巷口，早高峰的喇叭在身后响。"
        "手机忽然亮了，一块半透明的面板贴在视网膜上：【基础功法已植入】。"
        "旁边买豆浆的人还在吵架，没人看见他手一抖洒了半袋油条。"
    )
    text = (body + "\n\n") * 8
    assert visible_chars(text) >= 400
    assert serial_hook_flat(text, "ch1") is False


def test_serial_hook_flat_does_not_treat_discovery_word_as_hook() -> None:
    from app.writing.signals.prose import serial_hook_flat
    from app.writing.text_metrics import visible_chars

    body = "他突然发现今天的班和昨天一样。工位上没有人说话。窗外的天一直灰着。"
    text = (body + "\n\n") * 18
    assert visible_chars(text) >= 400
    assert serial_hook_flat(text, "ch1") is True


def test_serial_hook_flat_allows_world_already_running() -> None:
    from app.writing.signals.prose import serial_hook_flat
    from app.writing.text_metrics import visible_chars

    body = (
        "城门口的人把铜钱抛起来又接住。油饼摊的烟贴着墙走，底下混着汗和没扫干净的泥。"
        "他挤在最外一圈听人喊价。这城这样转了很久，他只是还站在最底下那一层。"
        "贴身布袋里那颗珠子隔着布烫他的肋骨，像提醒他别把这层日子当成全部。"
    )
    text = (body + "\n\n") * 6
    assert visible_chars(text) >= 400
    assert serial_hook_flat(text, "ch1") is False


def test_serial_hook_flat_still_flags_empty_grind() -> None:
    from app.writing.signals.prose import serial_hook_flat
    from app.writing.text_metrics import visible_chars

    body = "今天的班和昨天一样。工位上没有人说话。窗外的天一直灰着。"
    text = (body + "\n\n") * 18
    assert visible_chars(text) >= 400
    assert serial_hook_flat(text, "ch1") is True
