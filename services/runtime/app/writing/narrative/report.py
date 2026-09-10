"""L2 体检 Markdown。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.writing.narrative.spec import CORE_FEATURES, P3_TARGETS, SOURCE_CITATION


def _pct(value: float) -> str:
    if 0.0 <= value <= 1.0:
        return f"{value * 100:.1f}%"
    return f"{value:.2f}"


def _go_for_c(mechanism_inverted: bool, product_n: int, measured_off: bool | None) -> str:
    if product_n <= 0:
        return "做（无产品章；规则层已写反，按机制先验）" if mechanism_inverted else "暂缓（无产品章且规则未写反）"
    if measured_off is False:
        return "不做（证伪条件 D：本仓产出未偏离）"
    return "做"


def render_baseline_markdown(
    *,
    honesty: Mapping[str, Any],
    product_n: int,
    literary_n: int,
    rarity: float | None,
    agreement: float | None,
    batch_means: Mapping[str, float] | None = None,
    judge_mode: str = "unpublished",
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    e1 = honesty.get("exemplar_alignment") or {}
    e5 = honesty.get("staccato_dialogue") or {}
    lines = [
        "# 写作叙事基线体检（L2）",
        "",
        f"生成时间：{now} UTC",
        f"来源：{SOURCE_CITATION}",
        "",
        "本报告是 `docs/writing-quality-uplift-plan.md` §6 提示层改动的准入条件。",
        "L2 **不进产品 Turn**。LLM 评委只用于离线批处理。",
        "",
        "## 1. 仪器状态",
        "",
        f"- 评委模式：`{judge_mode}`",
        f"- 文学公版样本 n={literary_n}（人类基线语料，不是本仓产出）",
        f"- 本仓产品章稿 n={product_n}",
        f"- 评委自一致性：{agreement if agreement is not None else '未复测'}",
        f"- 稀有度百分位（相对发表 AI 云的代理）：{rarity if rarity is not None else '样本不足'}",
        "",
        "证伪条件 C：自一致性 < 0.75 的维度不得用于验收。",
        "",
        "## 2. 发表基线（Table 16）",
        "",
        "| 特征 | 人类 | AI | Gap | 本批 |",
        "|------|-----:|---:|----:|------|",
    ]
    batch = batch_means or {}
    for feat in CORE_FEATURES:
        local = batch.get(feat.key)
        local_s = _pct(local) if isinstance(local, (int, float)) else "—"
        if feat.kind == "prevalence":
            human_s, ai_s, gap_s = _pct(feat.human), _pct(feat.ai), f"{feat.gap * 100:.0f}pp"
        else:
            human_s, ai_s, gap_s = f"{feat.human:.2f}", f"{feat.ai:.2f}", f"{feat.gap:+.2f}"
        lines.append(f"| `{feat.key}` | {human_s} | {ai_s} | {gap_s} | {local_s} |")
    lines += [
        "",
        "## 3. L1 诚实化（方案 E，可无 LLM 跑）",
        "",
        f"- exemplar_alignment n={e1.get('n')} mean={e1.get('mean')} std={e1.get('std')} near_constant={e1.get('near_constant')} → `{e1.get('action')}`",
        f"- staccato vs scene_ratio corr={e5.get('corr_hit_vs_scene')} needs_decouple={e5.get('needs_decouple')}",
        "",
        "## 4. §6 C 条准入（证伪条件 D）",
        "",
        "| 条 | 机制是否写反 | 决议 |",
        "|----|--------------|------|",
        f"| C0 题材发散块 | 散文要求多样性（已测无效） | {_go_for_c(True, product_n, None)} |",
        f"| C1 禁止命名情绪 | 是（embodied 被设为唯一合法解） | {_go_for_c(True, product_n, None)} |",
        f"| C2 必须通过选择被看见 | 是 | {_go_for_c(True, product_n, None)} |",
        f"| C3 禁却说 | 是（禁掉人类偏高的破壁） | {_go_for_c(True, product_n, None)} |",
        f"| C4 禁第二场/新地点 | 是（反注水写成了反副线） | {_go_for_c(True, product_n, None)} |",
        f"| C5 时序只允许不要求 | 是 | {_go_for_c(True, product_n, None)} |",
        f"| C6 压缩 Don't | 否定密度 | {_go_for_c(True, product_n, None)} |",
        f"| C7 拆 meta_knowing | 是（说教与破壁绑死） | {_go_for_c(True, product_n, None)} |",
        "",
        "无产品章时不能主张「本仓产出未偏」。C 条改的是**规则文本**，机制对照 Table 16 已写反者放行。",
        "",
        "## 5. P3 主指标靶子（literary）",
        "",
        "| 特征 | 人类 | AI | 目标 |",
        "|------|-----:|---:|------|",
    ]
    labels = {
        "affect_embodied": "embodied ≤",
        "affect_named": "named ≥",
        "subplot_none": "no subplot ≤",
        "agency_protagonist": "protagonist choice ≤",
        "moral_ambivalent": "ambivalent ≥",
        "anachrony_intensity": "anachrony ≥",
    }
    for key, row in P3_TARGETS.items():
        feat = next(f for f in CORE_FEATURES if f.key == key)
        target = row.get("target_max", row.get("target_min"))
        if feat.kind == "prevalence":
            lines.append(
                f"| {labels[key]} | {_pct(feat.human)} | {_pct(feat.ai)} | {_pct(float(target))} |"
            )
        else:
            lines.append(
                f"| {labels[key]} | {feat.human:.2f} | {feat.ai:.2f} | {float(target):.2f} |"
            )
    lines += [
        "",
        "## 6. 守卫",
        "",
        "交付门通过率、length_short、golden、TTFB、patch_unnecessary、章内自相似度：本报告不替代 golden。",
        "",
    ]
    return "\n".join(lines) + "\n"
