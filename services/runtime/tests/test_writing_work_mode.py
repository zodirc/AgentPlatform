from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.writing.signals.spec import build_writing_spec_block, infer_fragment_from_duty
from app.writing.work_mode import (
    default_opening_duty,
    infer_chapter_element,
    infer_work_mode,
)


def test_infer_work_mode_web_serial() -> None:
    assert infer_work_mode("写一章长篇修仙小说的第一章") == "web_serial"
    assert infer_work_mode("玄幻网文，主角升级") == "web_serial"


def test_infer_work_mode_literary() -> None:
    assert infer_work_mode("仿鲁迅写一篇短篇小说") == "literary"
    assert infer_work_mode("写一篇故事") == "literary"


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
    assert "机构" in lit
    assert "强钩" in web or "悬念" in web


def test_spec_block_web_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写修仙长篇第一章")
    assert "work_mode: `web_serial`" in spec
    assert "过日子—加压—落下" not in spec


def test_spec_block_literary_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    spec = build_writing_spec_block("写一篇故事")
    assert "work_mode: `literary`" in spec


def test_platform_weights_differ_by_mode() -> None:
    wp_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "python"
        / "agent_contracts"
        / "writing_prefs.py"
    )
    spec = importlib.util.spec_from_file_location("wp", wp_path)
    assert spec and spec.loader
    wp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wp)
    lit = wp.platform_fragment_weights("literary")["plot_progress"]
    web = wp.platform_fragment_weights("web_serial")["plot_progress"]
    assert web["pacing"] > lit["pacing"]
    assert web["structure"] > lit["structure"]


def test_apply_work_mode_overlay() -> None:
    wp_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "python"
        / "agent_contracts"
        / "writing_prefs.py"
    )
    spec = importlib.util.spec_from_file_location("wp", wp_path)
    assert spec and spec.loader
    wp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wp)
    base = wp.platform_prefs_payload(work_mode="literary")
    web = wp.apply_work_mode_overlay(base, "web_serial")
    assert web["work_mode"] == "web_serial"
    pen = web["signal_penalties"]["mixed"]["serial_hook_flat"]
    assert pen < 0
