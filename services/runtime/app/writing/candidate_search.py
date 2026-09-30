"""作品候选的有界搜索合同：先显式铺开空间，再成文，最后按成文质量选择。

成文侧不以硬拒改写模型分布；用正例把下一 token 拉向书页简介层级。
差异来自热门网文那种不同的开书卖点，而不是清单式正交轴。
"""

from __future__ import annotations

import json
from typing import Any

from app.engine.state import user_message
from app.writing.work_reconstruction import (
    first_json_object,
    obvious_sample_overplot,
    obvious_sample_rhetoric,
)

DIRECTION_SET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ideas"],
    "properties": {
        "ideas": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 700},
        }
    },
}

CARD_SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["first", "second"],
    "properties": {
        "first": {"type": "integer", "minimum": -1, "maximum": 3},
        "second": {"type": "integer", "minimum": -1, "maximum": 3},
    },
}

RENDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "pitch"],
    "properties": {
        "title": {"type": "string", "minLength": 2, "maxLength": 16},
        "pitch": {"type": "string", "minLength": 20, "maxLength": 180},
    },
}

# 原创正例：只示范书页简介的抽象层级与口吻。
# 刻意贴近热门开书常见的几种卖点形态（文明尺度 / 异兆双界 / 分区世界），
# 而不是同一句“城市照常运转”的换皮。
_RENDER_EXEMPLARS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "修真者把漫长文明视为黑暗中的火种，在远超城市的尺度上前赴后继。",
        {
            "title": "余火纪年",
            "pitch": "倘若天地真是一片漫长的暗处，修真者也只会把自己燃成一点火。火再小，只要前赴后继，终会照见更大的世界。",
        },
    ),
    (
        "普通人身上忽然出现只属于另一层世界的异常标记，由此在表里两界往返。",
        {
            "title": "倒计时门",
            "pitch": "手臂上的倒计时清零时，人会坠入另一重钢铁与霓虹的世界；再清零，又回到原来的街道。被选中的人不止一个，秘密才刚露出边。",
        },
    ),
    (
        "灾变后的城市群被切开成编号特区，故事从其中一个特区内部长出来。",
        {
            "title": "灰域九区",
            "pitch": "灾变后的城市群被分成若干特区。九区有自己的规矩与边界；要从这里活下去，也只能从这里出发。",
        },
    ),
)

_DIRECTION_SYSTEM = """根据用户原话铺开四个真正不同的作品方向，不写书名和完整简介。

这是作品身份搜索，不是第一卷情节设计。像热门网文书城上会并列陈列的不同开书：每本都有自己让人点进去的核心卖点，而不是同一本换个封面。

每个方向用两三句话说清：这是怎样一片可延展的世界，主角大致从何处进入，读者将跟随怎样一种生活或天地。不要设计具体案件、连续场面、凶手、能力代价、亲属秘密、阶段结果或二选一难题。

只罗列写字楼、地铁、医院、老街、门派、世家和秘境，不等于形成作品身份。不要填写理论栏目，不解释构思过程。只输出四条 ideas。"""

_CARD_SELECTION_SYSTEM = """你是作品候选的终审，不是作者。只从已经写成的卡片中选最多两个；质量不够可以少选或全不选，用 -1 表示空位。

候选卡是让用户选择“哪一本书”，抽象层级应接近商业网文的开书简介，而不是小型大纲。优先选：
1. 有一眼可辨认的作品身份，并仍属于用户点名的题材；
2. 停在世界与人物位置，留下未定空间，不像第一卷梗概；
3. 两本放在一起时，像书城上两本不同的书，而不是同一卖点换标题。

简介可以偏气氛、世界宣言或宏观起点。cards 已按书页亲和度粗排。不要修改卡片，只返回编号。"""

_RENDER_SYSTEM = """把给定方向写成一张作品候选卡。

你写的是商业网文书页上的泛化简介，不是大纲，也不是第一章。读者开书前只需要感到：这是怎样一片世界，主角大致从何处进入，将走向怎样可延展的生活或天地。

前面的示例给出目标口吻与抽象层级。请延续那种书页感，并忠实于本次选中方向自身的卖点，不要写成第一卷情节。

两三句话即可。不要连续场面、查案、亲属嫌疑、能力代价、主题结论，也不要用“是……还是……”收束。

title 命名世界、时代、区域、意象或核心概念，不含书名号。pitch 通常六十到一百四十个汉字。只输出 title 和 pitch。"""


def listing_affinity(pitch: str) -> float:
    """书页简介亲和度：越高越接近采样目标。用于软排序，不作硬拒。"""
    body = (pitch or "").strip()
    if not body:
        return -100.0
    score = 0.0
    length = len(body)
    if 60 <= length <= 140:
        score += 3.0
    elif 40 <= length <= 180:
        score += 1.0
    else:
        score -= 2.0
    beats = body.count("。") + body.count("！") + body.count("？")
    if beats <= 3:
        score += 2.0
    elif beats == 4:
        score += 0.5
    else:
        score -= 2.0
    if obvious_sample_rhetoric(body):
        score -= 4.0
    if obvious_sample_overplot(body):
        score -= 3.0
    return score


def _shared_char_ratio(left: str, right: str) -> float:
    a = "".join((left or "").split())
    b = "".join((right or "").split())
    if not a or not b:
        return 0.0
    shared = 0
    window = 4
    if len(a) < window or len(b) < window:
        return 1.0 if a == b else 0.0
    seen = {a[i : i + window] for i in range(len(a) - window + 1)}
    for i in range(len(b) - window + 1):
        if b[i : i + window] in seen:
            shared += 1
    return shared / max(len(b) - window + 1, 1)


def pitches_near_duplicate(left: str, right: str) -> bool:
    """软重复：句式骨架过近，即使字面不完全相同。"""
    if not (left or "").strip() or not (right or "").strip():
        return False
    return _shared_char_ratio(left, right) >= 0.28


def diversify_selected_cards(
    cards: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """若终审两本过近，且池中存在更疏离的一对，则改挑那一对；否则保持原选。"""
    if len(selected) < 2 or len(cards) < 2:
        return selected
    first, second = selected[0], selected[1]
    if not pitches_near_duplicate(
        str(first.get("pitch") or ""),
        str(second.get("pitch") or ""),
    ):
        return selected
    best: list[dict[str, Any]] | None = None
    best_score = -1e9
    for i, left in enumerate(cards):
        for right in cards[i + 1 :]:
            lp = str(left.get("pitch") or "")
            rp = str(right.get("pitch") or "")
            if pitches_near_duplicate(lp, rp):
                continue
            score = listing_affinity(lp) + listing_affinity(rp)
            if score > best_score:
                best_score = score
                best = [left, right]
    return best if best is not None else selected


def direction_set_messages(
    user_text: str,
    *,
    discovery_pass: int = 1,
) -> list[dict[str, Any]]:
    pass_note = (
        ""
        if discovery_pass <= 1
        else "\n这是第二次独立搜索。不要参考、修补或续写旧卡。"
    )
    return [
        {"role": "system", "content": [{"type": "text", "text": _DIRECTION_SYSTEM}]},
        user_message(
            f"用户原话：{(user_text or '').strip()}{pass_note}\n\n只交四个短方向。"
        ),
    ]


def card_selection_messages(
    user_text: str,
    cards: list[dict[str, str]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        enumerate(cards),
        key=lambda item: listing_affinity(str(item[1].get("pitch") or "")),
        reverse=True,
    )
    payload = {
        "用户原话": (user_text or "").strip(),
        "候选卡片": [
            {
                "index": index,
                "title": str(card.get("title") or ""),
                "pitch": str(card.get("pitch") or ""),
                "listing_affinity": round(
                    listing_affinity(str(card.get("pitch") or "")), 2
                ),
            }
            for index, card in ordered
        ],
    }
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": _CARD_SELECTION_SYSTEM}],
        },
        user_message(json.dumps(payload, ensure_ascii=False)),
    ]


def render_messages(user_text: str, idea: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": [{"type": "text", "text": _RENDER_SYSTEM}]},
    ]
    for exemplar_idea, card in _RENDER_EXEMPLARS:
        messages.append(
            user_message(
                json.dumps(
                    {
                        "用户原话": "写一部长篇小说",
                        "选中方向": exemplar_idea,
                    },
                    ensure_ascii=False,
                )
            )
        )
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(card, ensure_ascii=False),
                    }
                ],
            }
        )
    messages.append(
        user_message(
            json.dumps(
                {
                    "用户原话": (user_text or "").strip(),
                    "选中方向": (idea or "").strip(),
                },
                ensure_ascii=False,
            )
        )
    )
    return messages


def parse_direction_set(raw: str) -> list[str]:
    data = first_json_object(raw)
    if not isinstance(data, dict):
        return []
    raw_ideas = data.get("ideas")
    if not isinstance(raw_ideas, list):
        return []
    ideas: list[str] = []
    for item in raw_ideas:
        idea = str(item or "").strip()[:700]
        if idea and idea not in ideas:
            ideas.append(idea)
    return ideas[:4]


def parse_card_selection(raw: str, count: int) -> list[int]:
    data = first_json_object(raw)
    if not isinstance(data, dict):
        return []
    out: list[int] = []
    for key in ("first", "second"):
        value = data.get(key)
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < count and index not in out:
            out.append(index)
    return out
