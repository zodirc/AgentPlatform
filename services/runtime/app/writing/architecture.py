"""写作路径开关。

corrected：Planner / Writer / Editor 隔离，signals 只做遥测。
minimal：只留写作包、声口、工具和用户消息。
legacy：冻结时的完整控制链，供对照，不作为默认。
"""

from __future__ import annotations

LEGACY = "legacy"
MINIMAL = "minimal"
CORRECTED = "corrected"

_ARCH = frozenset({LEGACY, MINIMAL, CORRECTED})

# 可自动修的机械问题。风格信号不在此列。
MECHANICAL_REPAIR_KEYS = frozenset(
    {
        "duplicate_paragraph",
        "broken_quotes",
        "bad_heading",
        "tool_duplicate",
        "locate_error",
    }
)

AESTHETIC_SIGNAL_KEYS = frozenset(
    {
        "staccato_uniform",
        "hinge_dense",
        "opening_institution",
        "lore_dump",
        "meta_knowing_high",
        "glue_heavy",
        "fragment_mismatch",
    }
)


def writing_architecture() -> str:
    from app.settings import settings

    raw = str(getattr(settings, "writing_architecture", CORRECTED) or CORRECTED).strip().lower()
    if raw in _ARCH:
        return raw
    return CORRECTED


def writer_sees_control_plane() -> bool:
    """legacy 才把评分、承诺、修复课和规划术语交给 Writer。"""
    return writing_architecture() == LEGACY


def commitment_hard_gate() -> bool:
    return writing_architecture() == LEGACY


def public_exemplar_rotation() -> bool:
    return writing_architecture() == LEGACY


def aesthetic_auto_patch() -> bool:
    return writing_architecture() == LEGACY


def net_signal_controls_patch() -> bool:
    return writing_architecture() == LEGACY


def style_signals_block_delivery() -> bool:
    return writing_architecture() == LEGACY


def inject_aesthetic_receipt() -> bool:
    return writing_architecture() == LEGACY


def strip_leaked_control(text: str) -> str:
    """Writer 上下文里若仍夹着承诺块，去掉。规划术语不从正文引用里猜。"""
    if writer_sees_control_plane():
        return text
    marker = "## Narrative commitment"
    idx = text.find(marker)
    if idx < 0:
        return text
    nxt = text.find("\n## ", idx + 3)
    if nxt < 0:
        return text[:idx].rstrip()
    return (text[:idx] + text[nxt:]).strip()
