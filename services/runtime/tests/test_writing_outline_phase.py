from __future__ import annotations

from pathlib import Path

from app.writing.outline_phase import (
    clear_style_lock,
    load_diverge_styles_volatile_block,
    outline_contract_ready,
    resolve_outline_phase,
    should_inject_diverge_styles,
    style_lock_exists,
    write_style_lock,
)


from app.writing.outline_arc import outline_style_committed


def _style_contract_block() -> str:
    return (
        "## 风格契约\n\n"
        "**路数**：凡人流\n\n"
        "**世界怎么运转**：灵石、丹药、引荐都要换；散修与内门隔着工分。"
        "记名弟子先干杂活，修仙先是生计，同门师徒也在算账。\n\n"
        "**文字与节奏**：惜命算计，打斗写消耗与代价，文笔平实，境界随视野慢慢露头。\n\n"
        "**开篇质地**：生计压力进门派，第一次危机常来自身边算计而非天降奇遇。\n\n"
        "**边界**：忌天才顿悟、第一章境界大全、默认水路渡口。\n"
    )


def _long_outline() -> str:
    return _style_contract_block() + (
        "## 开篇三章·世界契约\n\n"
        "### ch1\n环境：霜降边城，换防与军粮秤，谁管关隘。\n" + "细节。" * 30
        + "\n### ch2\n悬念：第二起逃役名册对不上，哨所无人应门。\n" + "细节。" * 30
        + "\n### ch3\n人物：沈禾被征丁，第一阶麻烦是今夜必须出关。\n" + "细节。" * 30
        + "\n主题倾向：边关资源博弈，读者跟算计与活路。\n"
        + "主线：沈禾要活着出关，挡着的是军法与粮道。\n"
    )


def test_diverge_without_lock_file(tmp_path: Path) -> None:
    phase = resolve_outline_phase(
        "写一章长篇玄幻小说第一章",
        workspace_root=tmp_path,
    )
    assert phase["outline_phase"] == "diverge"
    assert not style_lock_exists(tmp_path)


def test_contract_requires_style_lock(tmp_path: Path) -> None:
    outline = _long_outline()
    assert outline_contract_ready(outline, book_scope="long")
    phase_before = resolve_outline_phase(
        "写第一章",
        outline=outline,
        book_scope="long",
        workspace_root=tmp_path,
    )
    assert phase_before["outline_phase"] == "diverge"
    write_style_lock(outline, workspace_root=tmp_path)
    phase = resolve_outline_phase(
        "写第一章",
        outline=outline,
        book_scope="long",
        workspace_root=tmp_path,
    )
    assert phase["outline_phase"] == "contract"
    assert phase["style_locked"] is True


def test_should_inject_diverge_styles_without_lock(tmp_path: Path) -> None:
    assert should_inject_diverge_styles(
        "写一章长篇玄幻小说第一章",
        outline="",
        workspace_root=tmp_path,
    )
    outline = _long_outline()
    write_style_lock(outline, workspace_root=tmp_path)
    assert not should_inject_diverge_styles(
        "写一章长篇玄幻小说第一章",
        outline=outline,
        workspace_root=tmp_path,
    )


def test_diverge_styles_block_substantial() -> None:
    block = load_diverge_styles_volatile_block()
    assert "题材发散" in block
    assert "凡人流" in block
    assert "都市规则怪谈" in block
    assert "六路是六本" in block or "六本不同的书" in block
    assert "另起人名" in block
    assert "看见代价" not in block
    assert len(block) > 800


def test_should_not_inject_when_style_in_outline(tmp_path: Path) -> None:
    outline = _style_contract_block()
    assert outline_style_committed(outline)
    assert not should_inject_diverge_styles(
        "写一章长篇玄幻小说第一章",
        outline=outline,
        workspace_root=tmp_path,
    )


def test_early_style_lock_on_style_contract(tmp_path: Path) -> None:
    outline = _style_contract_block()
    assert not style_lock_exists(tmp_path)
    write_style_lock(outline, workspace_root=tmp_path)
    assert style_lock_exists(tmp_path)
    phase = resolve_outline_phase(
        "写一章长篇玄幻小说第一章",
        outline=outline,
        workspace_root=tmp_path,
    )
    assert phase["outline_phase"] == "diverge"
    assert phase["outline_style_committed"] is True


def test_clear_style_lock(tmp_path: Path) -> None:
    write_style_lock("outline body", workspace_root=tmp_path)
    assert style_lock_exists(tmp_path)
    clear_style_lock(tmp_path)
    assert not style_lock_exists(tmp_path)
