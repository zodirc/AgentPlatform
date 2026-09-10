# 写作叙事基线体检（L2）

生成时间：2026-09-10T03:21:58Z UTC
来源：Russell et al., StoryScope, COLM 2026, arXiv:2604.03136. Table 16 human/AI means; rarity Appendix H (human 0.71 vs AI 0.49).

本报告是 `docs/writing-quality-uplift-plan.md` §6 提示层改动的准入条件。
L2 **不进产品 Turn**。LLM 评委只用于离线批处理。

## 1. 仪器状态

- 评委模式：`baseline-no-llm`
- 文学公版样本 n=44（人类基线语料，不是本仓产出）
- 本仓产品章稿 n=0
- 评委自一致性：未复测
- 稀有度百分位（相对发表 AI 云的代理）：样本不足

证伪条件 C：自一致性 < 0.75 的维度不得用于验收。

## 2. 发表基线（Table 16）

| 特征 | 人类 | AI | Gap | 本批 |
|------|-----:|---:|----:|------|
| `thematic_explicitness` | 3.28 | 3.94 | -0.65 | — |
| `moral_weighting` | 3.26 | 3.68 | -0.42 | — |
| `thematic_unity` | 4.41 | 4.74 | -0.33 | — |
| `narratorial_theme_yes` | 52.0% | 77.0% | -25pp | — |
| `dialogue_philosophical` | 34.0% | 59.0% | -25pp | — |
| `reference_implicit_echoes` | 50.0% | 72.0% | -22pp | — |
| `affect_embodied` | 38.0% | 81.0% | -42pp | — |
| `setting_psych_mirror` | 3.58 | 4.07 | -0.49 | — |
| `eco_emphasis` | 2.83 | 3.21 | -0.38 | — |
| `sensory_olfactory` | 57.0% | 82.0% | -26pp | — |
| `sensory_density` | 3.66 | 3.93 | -0.26 | — |
| `interior_access` | 3.67 | 3.93 | -0.26 | — |
| `causal_continuity` | 3.92 | 4.20 | -0.28 | — |
| `spatial_granularity` | 2.27 | 2.53 | -0.26 | — |
| `agency_protagonist` | 46.0% | 69.0% | -23pp | — |
| `intro_external_desc` | 30.0% | 52.0% | -22pp | — |
| `subplot_none` | 57.0% | 79.0% | -22pp | — |
| `resolution_internal` | 27.0% | 47.0% | -21pp | — |
| `opening_spatial_ground` | 2.12 | 2.33 | -0.20 | — |
| `pre_threat_invest` | 2.76 | 2.99 | -0.23 | — |
| `intertextual_named` | 47.0% | 24.0% | 23pp | — |
| `reference_balanced` | 37.0% | 16.0% | 21pp | — |
| `fourth_wall` | 0.67 | 0.39 | +0.28 | — |
| `direct_reader_address` | 0.28 | 0.07 | +0.21 | — |
| `recontext_after_surprise` | 3.28 | 2.95 | +0.34 | — |
| `chrono_discontinuity` | 2.40 | 2.12 | +0.28 | — |
| `nonlinear_disclosure` | 1.96 | 1.68 | +0.28 | — |
| `anachrony_intensity` | 2.58 | 2.31 | +0.27 | — |
| `location_variety` | 1.34 | 1.08 | +0.26 | — |
| `dialogue_narration_ratio` | 2.95 | 2.70 | +0.24 | — |
| `subplot_parallel` | 42.0% | 21.0% | 22pp | — |
| `moral_ambivalent` | 59.0% | 38.0% | 21pp | — |
| `affect_named` | 29.0% | 8.0% | 21pp | — |

## 3. L1 诚实化（方案 E，可无 LLM 跑）

- exemplar_alignment n=31 mean=0.9299 std=0.0425 near_constant=True → `reduce_weight`
- staccato vs scene_ratio corr=None needs_decouple=False

## 4. §6 C 条准入（证伪条件 D）

| 条 | 机制是否写反 | 决议 |
|----|--------------|------|
| C0 题材发散块 | 散文要求多样性（已测无效） | 做（无产品章；规则层已写反，按机制先验） |
| C1 禁止命名情绪 | 是（embodied 被设为唯一合法解） | 做（无产品章；规则层已写反，按机制先验） |
| C2 必须通过选择被看见 | 是 | 做（无产品章；规则层已写反，按机制先验） |
| C3 禁却说 | 是（禁掉人类偏高的破壁） | 做（无产品章；规则层已写反，按机制先验） |
| C4 禁第二场/新地点 | 是（反注水写成了反副线） | 做（无产品章；规则层已写反，按机制先验） |
| C5 时序只允许不要求 | 是 | 做（无产品章；规则层已写反，按机制先验） |
| C6 压缩 Don't | 否定密度 | 做（无产品章；规则层已写反，按机制先验） |
| C7 拆 meta_knowing | 是（说教与破壁绑死） | 做（无产品章；规则层已写反，按机制先验） |

无产品章时不能主张「本仓产出未偏」。C 条改的是**规则文本**，机制对照 Table 16 已写反者放行。

## 5. P3 主指标靶子（literary）

| 特征 | 人类 | AI | 目标 |
|------|-----:|---:|------|
| embodied ≤ | 38.0% | 81.0% | 60.0% |
| named ≥ | 29.0% | 8.0% | 20.0% |
| no subplot ≤ | 57.0% | 79.0% | 65.0% |
| protagonist choice ≤ | 46.0% | 69.0% | 55.0% |
| ambivalent ≥ | 59.0% | 38.0% | 48.0% |
| anachrony ≥ | 2.58 | 2.31 | 2.45 |

## 6. 守卫

交付门通过率、length_short、golden、TTFB、patch_unnecessary、章内自相似度：本报告不替代 golden。

