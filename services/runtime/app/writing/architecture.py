"""写作路径。

只保留最小 Writer 主链：事实包、声口、工具和用户消息。
评分、承诺闸、公版轮换和审美自动补丁不再有开关。
"""

from __future__ import annotations

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


def strip_leaked_control(text: str) -> str:
    """Writer 上下文里若仍夹着承诺块，去掉。规划术语不从正文引用里猜。"""
    marker = "## Narrative commitment"
    idx = text.find(marker)
    if idx < 0:
        return text
    nxt = text.find("\n## ", idx + 3)
    if nxt < 0:
        return text[:idx].rstrip()
    return (text[:idx] + text[nxt:]).strip()
