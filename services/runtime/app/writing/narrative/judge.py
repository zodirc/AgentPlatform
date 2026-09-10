"""L2 LLM 评委：一次抽 30 维。只进离线脚本 / Ops lab，禁止产品 Turn 调用。"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from app.writing.narrative.spec import CORE_FEATURES, CORE_KEYS, CoreFeature

JudgeFn = Callable[[str, str], str]

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)

JUDGE_SYSTEM = """你是叙事特征标注员，不是写作教练。只根据给定正文打分。
输出一个 JSON 对象，键必须恰好是指定的 feature key。不要解释，不要markdown。
标尺：
- scale：1–5 李克特
- ordinal：按题面整数编码（破壁 0–4，地点 1–4，称呼读者 0–2）
- prevalence：0 或 1，表示该选项是否为本章主导
对短章仍要给数，不确定时靠近中间值，不要全填同一端。"""


def judge_user_prompt(text: str) -> str:
    lines = ["正文：", text.strip()[:12000], "", "特征："]
    for feat in CORE_FEATURES:
        extra = f" 选项={feat.option}" if feat.option else ""
        lines.append(f"- {feat.key} ({feat.kind}{extra}): {feat.question_zh}")
    lines.append("只输出 JSON。")
    return "\n".join(lines)


def parse_judge_payload(raw: str) -> dict[str, float]:
    blob = (raw or "").strip()
    if not blob:
        raise ValueError("empty_judge")
    match = _JSON_FENCE.search(blob)
    if match:
        blob = match.group(1).strip()
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("judge_not_json")
    data = json.loads(blob[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("judge_not_object")
    return _coerce_scores(data)


def _coerce_scores(data: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for feat in CORE_FEATURES:
        out[feat.key] = _coerce_one(feat, data.get(feat.key))
    extra = [k for k in data if k not in CORE_KEYS]
    if extra:
        out["_extra_keys"] = float(len(extra))
    return {k: v for k, v in out.items() if k != "_extra_keys"}


def _coerce_one(feat: CoreFeature, raw: Any) -> float:
    if isinstance(raw, bool):
        raw = 1.0 if raw else 0.0
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in {"yes", "true", feat.option}:
            raw = 1.0
        elif token in {"no", "false"}:
            raw = 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"bad_value:{feat.key}") from None
    if feat.kind == "prevalence":
        if value > 1.0:
            value = 1.0 if value >= 0.5 else 0.0
        return max(0.0, min(1.0, value))
    if feat.kind == "scale":
        return max(1.0, min(5.0, value))
    return max(0.0, min(5.0, value))


def score_text_with_judge(text: str, complete: JudgeFn) -> dict[str, float]:
    raw = complete(JUDGE_SYSTEM, judge_user_prompt(text))
    return parse_judge_payload(raw)


def self_agreement(runs: list[dict[str, float]]) -> float:
    """逐维一致率（scale/ordinal 容差 0.5；prevalence 必须相等）。近似 Krippendorff。"""
    if len(runs) < 2:
        return 1.0
    pairs = 0
    agree = 0.0
    for feat in CORE_FEATURES:
        vals = [float(row.get(feat.key, 0.0)) for row in runs]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                pairs += 1
                if feat.kind == "prevalence":
                    agree += 1.0 if abs(vals[i] - vals[j]) < 1e-9 else 0.0
                else:
                    agree += 1.0 if abs(vals[i] - vals[j]) <= 0.5 else 0.0
    return round(agree / pairs, 4) if pairs else 1.0
