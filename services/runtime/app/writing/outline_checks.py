"""规划与正文的软检查。最多三条，不打分，不硬拒。"""

from __future__ import annotations

import re

_SUMMARY_SKIP = re.compile(
    r"心中百感交集|终于意识到|经过一番|关系发生了微妙|更加坚定|正确的选择"
)
_SUDDEN = re.compile(r"突然|恰好|陌生")
_BECAUSE = re.compile(r"因为|由于|不能再")


def plan_issues(
    *,
    chapter: str = "",
    volume: str = "",
    user_wants_toc: bool = False,
) -> list[str]:
    """挂在 update_outline。字数和节拍只作观察，不构成开写门。"""
    if user_wants_toc:
        return []
    notes: list[str] = []
    body = (chapter or "").strip()
    if body and not _BECAUSE.search(body) and "行动" not in body and "选择" not in body:
        notes.append("章便条还看不出一次行动怎样换来下一次不同的做法。")
    if len(body) > 800:
        notes.append("章便条偏长，检查是否已经在预写对白或章末。")
    if _SUDDEN.search(body) and not _BECAUSE.search(body):
        notes.append("新出现的变化还没有写明是谁的哪一次行动带来的。")
    if volume and "卷问题" not in volume and "## 卷问题" not in volume:
        notes.append("这一卷还没有一个可以在卷末回答的问题。")
    return notes[:3]


def prose_shadow_issues(text: str) -> list[str]:
    """挂在 draft_section。只观察，不触发同轮重写。"""
    body = text or ""
    notes: list[str] = []
    if _SUMMARY_SKIP.search(body):
        notes.append("有句子在总结发现或选择，正文侧先核对场面是否已经发生。")
    if body.count("他感到") + body.count("她感到") >= 2:
        notes.append("心理句连着出现。删掉之后若动作不变，就不必留。")
    return notes[:3]
