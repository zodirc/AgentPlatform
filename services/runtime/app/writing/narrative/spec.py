"""StoryScope 30 维核心特征（中文改写）与发表基线。离线 L2 专用，不进产品 Turn。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ValueKind = Literal["scale", "ordinal", "prevalence"]


@dataclass(frozen=True)
class CoreFeature:
    """一条 Table 16 核心特征。"""

    key: str
    question_zh: str
    kind: ValueKind
    human: float
    ai: float
    gap: float
    lean: Literal["human", "ai"]
    option: str = ""


# Gap = Human − AI。负数 = AI 偏高。prevalence 用 0–1。
CORE_FEATURES: tuple[CoreFeature, ...] = (
    CoreFeature("thematic_explicitness", "主题/道德说教有多直白？", "scale", 3.28, 3.94, -0.65, "ai"),
    CoreFeature("moral_weighting", "道德/哲学问题有多压场？", "scale", 3.26, 3.68, -0.42, "ai"),
    CoreFeature("thematic_unity", "支线与点缀是否都服务同一主题？", "scale", 4.41, 4.74, -0.33, "ai"),
    CoreFeature("narratorial_theme_yes", "叙述者是否在人物视角之外点题？", "prevalence", 0.52, 0.77, -0.25, "ai", "yes"),
    CoreFeature("dialogue_philosophical", "对白是否主要在作哲理辩论？", "prevalence", 0.34, 0.59, -0.25, "ai", "philosophical"),
    CoreFeature("reference_implicit_echoes", "互文是不是以隐回声为主？", "prevalence", 0.50, 0.72, -0.22, "ai", "implicit_echoes"),
    CoreFeature("affect_embodied", "情绪是否以具身感觉传达？", "prevalence", 0.38, 0.81, -0.42, "ai", "embodied"),
    CoreFeature("setting_psych_mirror", "环境映照内心的程度？", "scale", 3.58, 4.07, -0.49, "ai"),
    CoreFeature("eco_emphasis", "自然/生态有多显眼？", "scale", 2.83, 3.21, -0.38, "ai"),
    CoreFeature("sensory_olfactory", "是否经常动用嗅觉？", "prevalence", 0.57, 0.82, -0.26, "ai", "olfactory"),
    CoreFeature("sensory_density", "感官描写有多密？", "scale", 3.66, 3.93, -0.26, "ai"),
    CoreFeature("interior_access", "叙述探进内心有多深？", "scale", 3.67, 3.93, -0.26, "ai"),
    CoreFeature("causal_continuity", "主因果链从起因到结局有多连续？", "scale", 3.92, 4.20, -0.28, "ai"),
    CoreFeature("spatial_granularity", "空间刻画有多细？", "ordinal", 2.27, 2.53, -0.26, "ai"),
    CoreFeature("agency_protagonist", "收束是否由主角选择驱动？", "prevalence", 0.46, 0.69, -0.23, "ai", "protagonist_choice"),
    CoreFeature("intro_external_desc", "主角是否以外貌介绍进场？", "prevalence", 0.30, 0.52, -0.22, "ai", "external_desc"),
    CoreFeature("subplot_none", "是否没有副线？", "prevalence", 0.57, 0.79, -0.22, "ai", "no_subplots"),
    CoreFeature("resolution_internal", "收束是否靠内在领悟？", "prevalence", 0.27, 0.47, -0.21, "ai", "internal"),
    CoreFeature("opening_spatial_ground", "开篇空间落地有多清楚？", "ordinal", 2.12, 2.33, -0.20, "ai"),
    CoreFeature("pre_threat_invest", "大危机前人物投资有多少？", "scale", 2.76, 2.99, -0.23, "ai"),
    CoreFeature("intertextual_named", "是否点名互文？", "prevalence", 0.47, 0.24, 0.23, "human", "explicit_named"),
    CoreFeature("reference_balanced", "互文是否显隐混用？", "prevalence", 0.37, 0.16, 0.21, "human", "balanced_mix"),
    CoreFeature("fourth_wall", "破壁程度？", "ordinal", 0.67, 0.39, 0.28, "human"),
    CoreFeature("direct_reader_address", "直接称呼读者的频率？", "ordinal", 0.28, 0.07, 0.21, "human"),
    CoreFeature("recontext_after_surprise", "意外之后重读前文有多深？", "scale", 3.28, 2.95, 0.34, "human"),
    CoreFeature("chrono_discontinuity", "时序跳跃有多频？", "scale", 2.40, 2.12, 0.28, "human"),
    CoreFeature("nonlinear_disclosure", "用跳时序来延迟揭晓的程度？", "scale", 1.96, 1.68, 0.28, "human"),
    CoreFeature("anachrony_intensity", "倒叙/预叙有多重？", "scale", 2.58, 2.31, 0.27, "human"),
    CoreFeature("location_variety", "地点种类有多少？", "ordinal", 1.34, 1.08, 0.26, "human"),
    CoreFeature("dialogue_narration_ratio", "对白相对叙述的比重？", "scale", 2.95, 2.70, 0.24, "human"),
    CoreFeature("subplot_parallel", "副线是否主题对位？", "prevalence", 0.42, 0.21, 0.22, "human", "thematically_parallel"),
    CoreFeature("moral_ambivalent", "对主角的道德立场是否暧昧？", "prevalence", 0.59, 0.38, 0.21, "human", "ambivalent"),
    CoreFeature("affect_named", "情绪是否被明确命名？", "prevalence", 0.29, 0.08, 0.21, "human", "explicit_labels"),
)

FEATURE_BY_KEY = {f.key: f for f in CORE_FEATURES}
CORE_KEYS: tuple[str, ...] = tuple(f.key for f in CORE_FEATURES)

# P3 literary 主指标（方案文档 §12）。
P3_TARGETS: dict[str, dict[str, float]] = {
    "affect_embodied": {"human": 0.38, "ai": 0.81, "target_max": 0.60},
    "affect_named": {"human": 0.29, "ai": 0.08, "target_min": 0.20},
    "subplot_none": {"human": 0.57, "ai": 0.79, "target_max": 0.65},
    "agency_protagonist": {"human": 0.46, "ai": 0.69, "target_max": 0.55},
    "moral_ambivalent": {"human": 0.59, "ai": 0.38, "target_min": 0.48},
    "anachrony_intensity": {"human": 2.58, "ai": 2.31, "target_min": 2.45},
}

SOURCE_CITATION = (
    "Russell et al., StoryScope, COLM 2026, arXiv:2604.03136. "
    "Table 16 human/AI means; rarity Appendix H (human 0.71 vs AI 0.49)."
)


def numeric_baseline(feature: CoreFeature, which: Literal["human", "ai"]) -> float:
    return float(feature.human if which == "human" else feature.ai)
