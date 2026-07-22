"""Plan suggest complexity scoring (docs/26). Soft hint only — never forces plan."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

PLAN_PREFIX = "【Plan 模式】"
EXECUTE_PREFIX = "【执行计划】"

_NUMBERED_GOAL = re.compile(r"(?m)^\s*(?:\d+[\.\)、]|[-*•]\s+\S)")
_GOAL_JOIN = re.compile(
    r"(?:然后|接着|并且|同时|另外|还要|此外|and then|also|finally)\s*",
    re.I,
)
_PATH_AT = re.compile(r"@([\w./-]+\.(?:md|txt|py|ts|tsx|json|yaml|yml)|[\w./-]+)")
_CHAPTER_REF = re.compile(r"第\s*[0-9一二三四五六七八九十百零两]+\s*章")
_EXPLICIT_PLAN = re.compile(
    r"先规划|先做计划|给个方案|先列步骤|分步(?:做|完成|实现)?|"
    r"make a plan|plan first|before (?:we |you )?(?:start|begin|implement)",
    re.I,
)
_CONTINUE_ONLY = re.compile(
    r"^(?:继续|接着写|往下写|续写|再顺一下|继续写|continue)\s*[。.!！]?$",
    re.I,
)
_CONTINUE_LOOSE = re.compile(r"(?:继续|接着写|往下写|续写|再顺一下)")
_MICRO = re.compile(r"语气|错字|错别字|标点|改一句|\btypo\b|\bfix the typo\b", re.I)

_FALLBACK_CONFIG: dict[str, Any] = {
    "cooldown_ms": 1_800_000,
    "abs_min_len": 8,
    "soft_min_len": 24,
    "scores": {
        "multi_numbered": 4,
        "multi_join": 2,
        "explicit_plan": 4,
        "multi_path": 2,
        "high_risk_per_hit": 2,
        "high_risk_cap": 4,
        "continue_refine": -3,
        "single_micro": -2,
    },
    "threshold": {
        "writing": 4,
        "agent": 4,
        "interview": 3,
        "default": 4,
    },
    "high_risk_tokens": [
        "重构",
        "重写全书",
        "迁移",
        "批量改",
        "批量更新",
        "批量替换",
        "refactor",
        "migrate",
        "rewrite the entire",
        "rewrite the whole",
        "rewrite entire",
        "rewrite whole",
    ],
    "reasons": {
        "multi_numbered": "检测到多个独立目标",
        "multi_join": "请求包含多个连贯目标",
        "explicit_plan": "你提到先规划再动手",
        "multi_path": "请求涉及多处文稿或文件",
        "high_risk_verb": "改动面较大，建议先拆步",
    },
}


def plan_suggest_weights_candidates() -> list[Path]:
    """Candidate weight files (container + repo checkout + local fallback).

    Do not assume a fixed ``parents[N]`` depth: in the image ``__file__`` is
    ``/app/app/controller/...`` (shallow), while a git checkout is deeper.
    """
    here = Path(__file__).resolve()
    seen: list[Path] = []

    def _add(path: Path) -> None:
        if path not in seen:
            seen.append(path)

    _add(Path("/app/packages/contracts/plan_suggest/weights.json"))
    for parent in here.parents:
        _add(parent / "packages" / "contracts" / "plan_suggest" / "weights.json")
    _add(here.parent / "plan_suggest_weights.json")
    return seen


def resolve_plan_suggest_weights_path() -> Path | None:
    for path in plan_suggest_weights_candidates():
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=1)
def load_plan_suggest_config() -> dict[str, Any]:
    path = resolve_plan_suggest_weights_path()
    if path is None:
        return dict(_FALLBACK_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return dict(_FALLBACK_CONFIG)
    merged = dict(_FALLBACK_CONFIG)
    merged.update({k: v for k, v in data.items() if k in merged or k in {"version", "description", "scores", "threshold", "high_risk_tokens", "reasons", "cooldown_ms", "abs_min_len", "soft_min_len"}})
    if isinstance(data.get("scores"), dict):
        scores = dict(_FALLBACK_CONFIG["scores"])
        scores.update({k: int(v) for k, v in data["scores"].items()})
        merged["scores"] = scores
    if isinstance(data.get("threshold"), dict):
        thr = dict(_FALLBACK_CONFIG["threshold"])
        thr.update({k: int(v) for k, v in data["threshold"].items()})
        merged["threshold"] = thr
    if isinstance(data.get("reasons"), dict):
        reasons = dict(_FALLBACK_CONFIG["reasons"])
        reasons.update({k: str(v) for k, v in data["reasons"].items()})
        merged["reasons"] = reasons
    if isinstance(data.get("high_risk_tokens"), list):
        merged["high_risk_tokens"] = [str(x) for x in data["high_risk_tokens"]]
    for key in ("cooldown_ms", "abs_min_len", "soft_min_len"):
        if key in data:
            merged[key] = int(data[key])
    return merged


def reload_plan_suggest_config() -> dict[str, Any]:
    load_plan_suggest_config.cache_clear()
    return load_plan_suggest_config()


@dataclass(frozen=True)
class PlanSuggestWeights:
    """Tunable weights (docs/26). Prefer editing packages/contracts/plan_suggest/weights.json."""

    multi_numbered: int = 4
    multi_join: int = 2
    explicit_plan: int = 4
    multi_path: int = 2
    high_risk_per_hit: int = 2
    high_risk_cap: int = 4
    continue_refine: int = -3
    single_micro: int = -2
    threshold_writing: int = 4
    threshold_agent: int = 4
    threshold_interview: int = 3
    abs_min_len: int = 8
    soft_min_len: int = 24

    def threshold_for(self, scenario_id: str | None) -> int:
        key = (scenario_id or "writing").strip().lower()
        if key == "agent":
            return self.threshold_agent
        if key == "interview":
            return self.threshold_interview
        return self.threshold_writing

    def to_dict(self) -> dict[str, int]:
        return {
            "multi_numbered": self.multi_numbered,
            "multi_join": self.multi_join,
            "explicit_plan": self.explicit_plan,
            "multi_path": self.multi_path,
            "high_risk_per_hit": self.high_risk_per_hit,
            "high_risk_cap": self.high_risk_cap,
            "continue_refine": self.continue_refine,
            "single_micro": self.single_micro,
            "threshold_writing": self.threshold_writing,
            "threshold_agent": self.threshold_agent,
            "threshold_interview": self.threshold_interview,
            "abs_min_len": self.abs_min_len,
            "soft_min_len": self.soft_min_len,
        }

    def to_config_file_dict(self) -> dict[str, Any]:
        """Shape matching packages/contracts/plan_suggest/weights.json."""
        cfg = load_plan_suggest_config()
        return {
            "version": cfg.get("version", 1),
            "description": cfg.get(
                "description",
                "Plan suggest scoring (docs/26).",
            ),
            "cooldown_ms": int(cfg.get("cooldown_ms", 1_800_000)),
            "abs_min_len": self.abs_min_len,
            "soft_min_len": self.soft_min_len,
            "scores": {
                "multi_numbered": self.multi_numbered,
                "multi_join": self.multi_join,
                "explicit_plan": self.explicit_plan,
                "multi_path": self.multi_path,
                "high_risk_per_hit": self.high_risk_per_hit,
                "high_risk_cap": self.high_risk_cap,
                "continue_refine": self.continue_refine,
                "single_micro": self.single_micro,
            },
            "threshold": {
                "writing": self.threshold_writing,
                "agent": self.threshold_agent,
                "interview": self.threshold_interview,
                "default": self.threshold_writing,
            },
            "high_risk_tokens": list(cfg.get("high_risk_tokens") or []),
            "reasons": dict(cfg.get("reasons") or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, int] | None) -> PlanSuggestWeights:
        if not data:
            return cls.from_config()
        base = cls.from_config()
        allowed = set(cls.__dataclass_fields__.keys())
        updates = {k: int(v) for k, v in data.items() if k in allowed}
        return replace(base, **updates)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> PlanSuggestWeights:
        cfg = config or load_plan_suggest_config()
        scores = cfg.get("scores") or {}
        thr = cfg.get("threshold") or {}
        return cls(
            multi_numbered=int(scores.get("multi_numbered", 4)),
            multi_join=int(scores.get("multi_join", 2)),
            explicit_plan=int(scores.get("explicit_plan", 4)),
            multi_path=int(scores.get("multi_path", 2)),
            high_risk_per_hit=int(scores.get("high_risk_per_hit", 2)),
            high_risk_cap=int(scores.get("high_risk_cap", 4)),
            continue_refine=int(scores.get("continue_refine", -3)),
            single_micro=int(scores.get("single_micro", -2)),
            threshold_writing=int(thr.get("writing", thr.get("default", 4))),
            threshold_agent=int(thr.get("agent", thr.get("default", 4))),
            threshold_interview=int(thr.get("interview", 3)),
            abs_min_len=int(cfg.get("abs_min_len", 8)),
            soft_min_len=int(cfg.get("soft_min_len", 24)),
        )


def get_default_weights() -> PlanSuggestWeights:
    return PlanSuggestWeights.from_config()


@dataclass(frozen=True)
class PlanSuggestDecision:
    suggest: bool
    score: int
    reasons: list[str]
    signals: list[str]


def plan_suggest_threshold(
    scenario_id: str | None = None,
    *,
    weights: PlanSuggestWeights | None = None,
) -> int:
    w = weights or get_default_weights()
    return w.threshold_for(scenario_id)


def evaluate_plan_suggest(
    message: str,
    *,
    scenario_id: str | None = None,
    cooldown_active: bool = False,
    weights: PlanSuggestWeights | None = None,
) -> PlanSuggestDecision:
    cfg = load_plan_suggest_config()
    w = weights or PlanSuggestWeights.from_config(cfg)
    reasons_map: dict[str, str] = dict(cfg.get("reasons") or {})
    risk_tokens: list[str] = list(cfg.get("high_risk_tokens") or [])

    text = message.strip()
    signals: list[str] = []
    reasons: list[str] = []
    score = 0

    def push(sid: str, delta: int) -> None:
        nonlocal score
        signals.append(sid)
        score += delta
        reason = reasons_map.get(sid)
        if reason and len(reasons) < 2 and reason not in reasons:
            reasons.append(reason)

    if cooldown_active:
        return PlanSuggestDecision(False, 0, [], ["cooldown_active"])

    if not text or len(text) < w.abs_min_len:
        return PlanSuggestDecision(False, 0, [], ["too_short"])

    if text.startswith(PLAN_PREFIX) or text.startswith(EXECUTE_PREFIX):
        return PlanSuggestDecision(False, 0, [], ["already_plan_prefix"])

    if _CONTINUE_ONLY.match(text):
        return PlanSuggestDecision(False, 0, [], ["continue_refine"])

    numbered = len(_NUMBERED_GOAL.findall(text))
    if numbered >= 3:
        push("multi_numbered", w.multi_numbered)

    joins = len(_GOAL_JOIN.findall(text))
    if joins >= 2 and len(text) >= 40:
        push("multi_join", w.multi_join)

    if _EXPLICIT_PLAN.search(text):
        push("explicit_plan", w.explicit_plan)

    at_paths = len(_PATH_AT.findall(text))
    chapters = len(_CHAPTER_REF.findall(text))
    if at_paths >= 2 or chapters >= 2:
        push("multi_path", w.multi_path)

    lower = text.lower()
    risk_hits = [
        tok
        for tok in risk_tokens
        if (tok in lower if tok.isascii() else tok in text)
    ]
    if risk_hits:
        push(
            "high_risk_verb",
            min(w.high_risk_cap, w.high_risk_per_hit * len(risk_hits)),
        )

    strong = (
        "multi_numbered" in signals
        or "explicit_plan" in signals
        or "high_risk_verb" in signals
    )
    if len(text) < w.soft_min_len and not strong:
        return PlanSuggestDecision(False, 0, [], ["too_short"])

    if _CONTINUE_LOOSE.search(text) and numbered < 3:
        push("continue_refine", w.continue_refine)

    if _MICRO.search(text):
        push("single_micro", w.single_micro)

    threshold = w.threshold_for(scenario_id)
    suggest = score >= threshold
    return PlanSuggestDecision(
        suggest=suggest,
        score=score,
        reasons=reasons[:2] if suggest else [],
        signals=signals,
    )


def detect_plan_hint(message: str, *, scenario_id: str | None = None) -> str | None:
    """Soft runtime hint mirrored from Web scoring. Never forces tools."""
    decision = evaluate_plan_suggest(message, scenario_id=scenario_id)
    if not decision.suggest:
        return None
    reason = decision.reasons[0] if decision.reasons else "complex request"
    return (
        f"{reason}; consider calling update_plan once before other tools "
        "(optional — not required)."
    )
