from __future__ import annotations

from pathlib import Path

from app.writing.focus import (
    build_work_surface_block,
    infer_focus_section_id,
    wants_full_manuscript_read,
)
from app.writing.manuscript import upsert_section


def test_infer_focus_chinese_and_ch() -> None:
    available = ["ch1", "ch2", "ch3"]
    assert infer_focus_section_id("写第三章", available) == "ch3"
    assert infer_focus_section_id("继续写 ch2", available) == "ch2"
    assert infer_focus_section_id("接着写", available) == "ch3"
    assert infer_focus_section_id("下一章", available) == "ch4"
    assert infer_focus_section_id("把这章写完", available) == "ch3"


def test_work_surface_includes_prev_tail(tmp_path: Path) -> None:
    doc = ""
    doc = upsert_section(doc, "ch1", "AAAA" * 100)
    doc = upsert_section(doc, "ch2", "BBBB" * 50)
    drafts = tmp_path / ".agent" / "work" / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")

    block = build_work_surface_block(
        "写第二章",
        workspace_root=tmp_path,
        max_chars=8000,
        prev_tail_chars=80,
        focus_max_chars=5000,
    )
    assert "focus: `ch2`" in block
    assert "上一章已发生的结尾" in block
    assert "不续写最后一句" in block
    assert "承接" not in block
    assert "Focus (`ch2`)" in block


def test_work_surface_pins_outline_job(tmp_path: Path) -> None:
    doc = upsert_section("", "ch3", "本章正文。" * 20)
    drafts = tmp_path / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "manuscript.md").write_text(doc, encoding="utf-8")
    (tmp_path / "outline.md").write_text(
        "主线：沈禾要保住铺子，挡着的是粮行。\n\n"
        "# 第三章\n加压：核秤，不摊牌。\n",
        encoding="utf-8",
    )
    block = build_work_surface_block("写第三章", workspace_root=tmp_path)
    assert "### 写作包" in block
    assert "保住铺子" not in block
    assert "当前章段" not in block
    assert "核秤" in block
    assert "铺垫" not in block


_LAYERED = """## 这本书
《心相工坊》。点选简介原文。

## 世界入口
读者跟着陆沉舟进入。心相先作为一门普通但不体面的生意出现。

## 当前阶段
工坊只收拾边角异常。阶段结束时他留下第一件本该上交的东西。

## 远处
后一阶段记忆开始在城里流通，此处不写具体章节。

## 第一章
章节作用：心相从职业背景变成会改变普通人关系的现实。
当前章段：陆沉舟接到一个七岁的孩子。孩子每天醒来都叫母亲阿姨，却记得她煮粥总忘关小火。母亲不肯让工坊取走心相。陆沉舟得先弄清孩子忘掉的是母亲，还是母亲这个称呼。封锁组明早来接人。

## 第二章
章节作用：陆沉舟留下本该销毁的记忆，封锁组开始直接检查工坊。
当前章段：孩子被带走后，取出的记忆还在抽屉里，手续上写着已经销毁。母亲回来要它。机构下午来验工坊。陆沉舟若交出去就解释不了空盒。

## 第三章
章节作用：母亲开始知道工坊没有上交那段记忆。
当前章段：母亲第二次来时不再只问孩子，她要看销毁手续上的空盒。陆沉舟若承认留下了记忆，封锁组下午的清点就对不上。
"""


def test_write_surface_splits_stage_role_and_brief(tmp_path: Path) -> None:
    (tmp_path / "outline.md").write_text(_LAYERED, encoding="utf-8")
    ch1 = build_work_surface_block("写第一章", workspace_root=tmp_path, max_chars=8000)
    assert "### 写作包" in ch1
    assert "### 世界入口" not in ch1
    assert "### 章节作用" not in ch1
    assert "生意" not in ch1
    assert "边角异常" not in ch1
    assert "煮粥" in ch1
    assert "城里流通" not in ch1

    ch2 = build_work_surface_block("写第二章", workspace_root=tmp_path, max_chars=8000)
    assert "### 世界入口" not in ch2
    assert "不体面的生意" not in ch2
    assert "边角异常" not in ch2
    assert "抽屉" in ch2
    assert "煮粥" not in ch2
    assert "职业背景" not in ch2
    assert "城里流通" not in ch2
    assert "第二次来" not in ch2

    ch3 = build_work_surface_block("写第三章", workspace_root=tmp_path, max_chars=8000)
    assert "不体面的生意" not in ch3
    assert "边角异常" not in ch3
    assert "空盒" in ch3
    assert "煮粥" not in ch3
    assert "城里流通" not in ch3


def test_wants_full_manuscript_read() -> None:
    assert wants_full_manuscript_read("请通读全文检查人称", full_flag=False) is True
    assert wants_full_manuscript_read("写第三章", full_flag=False) is False
    assert wants_full_manuscript_read("", full_flag=True) is True
