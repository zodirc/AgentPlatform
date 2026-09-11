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
        message="写一章长篇修真小说的第一章, 现代都市题材",
    )
    assert "得到" in urban or "发现" in urban
    assert "觉醒" in urban
    assert "有人的日子" not in urban
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
    spec = build_writing_spec_block("写一章长篇玄幻小说里的第一章 严格模式")
    assert "work_mode: `web_serial`" in spec
    assert "book_scope: `long`" in spec
    assert "开篇" in spec
    assert "评分切片" in spec
    assert "fragment: `plot_progress`" in spec
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
    lit_tex = wp.platform_fragment_weights("literary")["worldview_texture"]
    web_tex = wp.platform_fragment_weights("web_serial")["worldview_texture"]
    assert web_tex["exemplar_alignment"] == 0.0
    assert lit_tex["exemplar_alignment"] == 0.0
    assert web_tex["pacing"] > lit_tex["pacing"]
    assert web_tex["structure"] > lit_tex["structure"]


def test_apply_work_mode_overlay() -> None:
    wp = _writing_prefs()
    base = wp.platform_prefs_payload(work_mode="literary")
    web = wp.apply_work_mode_overlay(base, "web_serial")
    assert web["work_mode"] == "web_serial"
    pen = web["signal_penalties"]["mixed"]["serial_hook_flat"]
    assert pen < 0
    assert web["signal_penalties"]["mixed"]["all_explained"] < 0
    assert web["signal_penalties"]["mixed"]["escalation_flat"] < 0
    assert web["signal_penalties"]["mixed"]["premise_novella"] < 0
    assert web["signal_rewards"]["mixed"]["price_paid_visible"] > 0
    assert web["signal_rewards"]["mixed"]["world_layer_visible"] > 0


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


def _pad_web_serial(body: str) -> str:
    return (body + "\n\n") * 12


def test_all_explained_flags_origin_lecture_without_blank() -> None:
    from app.writing.signals.prose import all_explained
    from app.writing.text_metrics import visible_chars

    explained = _pad_web_serial(
        "系统原来是宗门内门发下来的功法面板。其实是师兄提前把灵气灌进他丹田。"
        "这是因为那天他在巷口签收了一枚铜印。真相是那只手来自内门执事。"
    )
    blank = _pad_web_serial(
        "系统亮了。铜印落进掌心。那只手从柜门里伸出来。说不清它从哪来，来源不明。"
        "他问了一句，没人解释。功法已经入体。"
    )
    assert visible_chars(explained) >= 400
    assert all_explained(explained, work_mode="web_serial") is True
    assert all_explained(blank, work_mode="web_serial") is False
    assert all_explained(explained, work_mode="literary") is False
    from app.writing.signals.scorer import score_writing_fragment

    prefs = _writing_prefs().platform_prefs_payload(work_mode="web_serial")
    out = score_writing_fragment(
        explained, fragment_declared="mixed", section_id="ch1", prefs=prefs
    )
    assert any(p["key"] == "all_explained" for p in out["penalties"])


def test_escalation_flat_and_price_paid_visible() -> None:
    from app.writing.signals.prose import escalation_flat, price_paid_visible
    from app.writing.text_metrics import visible_chars

    smooth = _pad_web_serial(
        "系统亮了。他催动功法，灵气入体，一拳把对手打退。面板跳出下一阶任务。"
        "巷口的人让开。他接着走。"
    )
    retreat = _pad_web_serial(
        "系统亮了。他催动功法还是打不过，跑了。账单当晚就来收，寿命少了三年。"
        "面板上只剩一次。"
    )
    paid = _pad_web_serial(
        "功法入体之后他催动一次。相册里她那一格空了。山高 3000 米，已支付 1 米。"
        "系统把这一米扣了。"
    )
    assert visible_chars(smooth) >= 400
    assert escalation_flat(smooth, work_mode="web_serial") is True
    assert escalation_flat(retreat, work_mode="web_serial") is False
    assert price_paid_visible(paid, work_mode="web_serial") is True
    assert price_paid_visible(smooth, work_mode="web_serial") is False
    assert escalation_flat(smooth, work_mode="literary") is False

    from app.writing.signals.scorer import score_writing_fragment

    prefs = _writing_prefs().platform_prefs_payload(work_mode="web_serial")
    opening = score_writing_fragment(
        smooth,
        fragment_declared="mixed",
        section_id="ch1",
        prefs=prefs,
        chapter_position="opening",
    )
    assert any(p["key"] == "escalation_flat" for p in opening["penalties"])
    rising = score_writing_fragment(
        smooth,
        fragment_declared="mixed",
        section_id="ch5",
        prefs=prefs,
        chapter_position="rising",
    )
    assert not any(p["key"] == "escalation_flat" for p in rising["penalties"])


def test_premise_novella_and_world_layer_signals() -> None:
    from app.writing.signals.prose import premise_novella, world_layer_visible
    from app.writing.signals.scorer import score_writing_fragment
    from app.writing.text_metrics import visible_chars

    closed = _pad_web_serial(
        "系统亮了。他催动功法，救回母亲并保住了手术押金，本市航线被掀掉。"
        "巷口的人让开。他接着走，决定当不当下一任持票人。"
    )
    layered = _pad_web_serial(
        "系统亮了。隐世那一层的序列职阶在面板上跳出来，秘境入口就在港区下面。"
        "他催动功法，账单当晚到账。山高 3000 米。"
    )
    assert visible_chars(closed) >= 400
    assert premise_novella(closed, work_mode="web_serial") is True
    assert world_layer_visible(closed, work_mode="web_serial") is False
    assert premise_novella(layered, work_mode="web_serial") is False
    assert world_layer_visible(layered, work_mode="web_serial") is True
    assert premise_novella(closed, work_mode="literary") is False

    prefs = _writing_prefs().platform_prefs_payload(work_mode="web_serial")
    bad = score_writing_fragment(
        closed,
        fragment_declared="mixed",
        section_id="ch1",
        prefs=prefs,
        chapter_position="opening",
    )
    assert any(p["key"] == "premise_novella" for p in bad["penalties"])
    good = score_writing_fragment(
        layered,
        fragment_declared="mixed",
        section_id="ch1",
        prefs=prefs,
        chapter_position="opening",
    )
    assert any(r["key"] == "world_layer_visible" for r in good["rewards"])
    quiet = score_writing_fragment(
        layered,
        fragment_declared="mixed",
        section_id="ch5",
        prefs=prefs,
        chapter_position="rising",
    )
    assert not any(r["key"] == "world_layer_visible" for r in quiet["rewards"])
