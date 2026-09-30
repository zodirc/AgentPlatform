"""候选立意的独立 shadow 标注。

评委看用户原话与已形成的 premise/card，返回固定原因码；不靠简介正则，
也不把原因码送回原卡片修补。shadow 阶段调用方始终保留卡片。
"""

from __future__ import annotations

import json
from typing import Any

INTENT_CODES = (
    "no_human_pull",
    "genre_decorative",
    "noun_graft",
    "moral_pre_solved",
    "no_serial_engine",
)

# 第一版全部 shadow。高置信硬拒要等固定集盲评之后另开。
SHADOW_CODES = frozenset(INTENT_CODES)

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(INTENT_CODES),
    "properties": {code: {"type": "boolean"} for code in INTENT_CODES},
}

GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent"],
    "properties": {"intent": INTENT_SCHEMA},
}

_GATE_SYSTEM = """你是作品前提标注员，不是改稿人。独立判断给定候选，不提供修改建议。

只检查五件事：
- no_human_pull：候选只介绍工作或设定，没有让读者继续跟随主角的欲望、能力、好奇、关系、处境或成长；
- genre_decorative：候选没有兑现用户所选题材通常承诺的核心体验，只借用了类型名词；
- noun_graft：先选日常职业、设施、行政或合同流程，再把它改名成超自然系统，当作主要创意；
- moral_pre_solved：叙述预先宣布主角天然正确，其他人只负责冷酷阻拦；
- no_serial_engine：十章后只能再投一个秘密、异常或任务才能继续。

职业或设施出现本身不算失败。只根据结构判断。每项必须给 true/false，只输出 JSON。"""


def gate_messages(
    user_text: str,
    *,
    title: str,
    pitch: str,
    premise: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = {
        "用户原话": (user_text or "").strip(),
        "书名": (title or "").strip(),
        "简介": (pitch or "").strip(),
        "形成前提": premise if isinstance(premise, dict) else {},
    }
    return [
        {"role": "system", "content": [{"type": "text", "text": _GATE_SYSTEM}]},
        {
            "role": "user",
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        },
    ]


def intent_codes_from_payload(data: dict[str, Any] | None) -> list[str]:
    """从候选 JSON 的 intent 对象收集为真的原因码。缺字段不算失败。"""
    if not isinstance(data, dict):
        return []
    raw = data.get("intent")
    if not isinstance(raw, dict):
        return []
    codes: list[str] = []
    for code in INTENT_CODES:
        if raw.get(code) is True:
            codes.append(code)
    return codes


def parse_gate_payload(raw: str) -> list[str]:
    text = (raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (TypeError, json.JSONDecodeError):
        return []
    return intent_codes_from_payload(data if isinstance(data, dict) else None)


def shadow_only(codes: list[str]) -> list[str]:
    """当前仍只记录、不丢卡的原因码。"""
    return [code for code in codes if code in SHADOW_CODES]
