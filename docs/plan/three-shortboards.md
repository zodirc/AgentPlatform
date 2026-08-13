# 三大短板：怎么理解

> 2026-08-13 · 深度评分中的三点说明（非实施手册）

能力主路径已齐之后，主要短板是三件**不同性质**的事：

| 短板 | 问的是 |
|------|--------|
| **巨模块** | 以后好不好改？ |
| **宪法泄漏** | 架构规矩还守不守？ |
| **效果锚未闭合** | 能力有没有被数字钉死？ |

不是「跑不起来」，是可维护性、宪法执行、效果证明还没跟设计叙事对齐。

---

## 1. 巨模块

不是功能做错了，而是**代码重力**：单文件过大，改一处风险与审阅成本过高。

典型量级：

| 约 LOC | 落点 |
|--------|------|
| 5900 | `services/web/src/ops/OfficialBenchPage.tsx` |
| 3300 | `services/api/app/services/ops/official_agent_path.py` |
| 3100 | `services/runtime/app/tools/core/tools.py` |
| 1300+ | `useWorkbench.ts` 等热路径 |

功能可能都对，但演进会被文件体量拖死。类比：发动机能跑，整车焊成一块铁——修火花塞也要拆半辆车。

---

## 2. 宪法泄漏

正文硬约束：**一个 Engine，差异只走 Profile / ToolScope，禁止 `if scenario == "…"`。**

实现里仍有硬编码场景分支，例如：

- `agent_engine.py`：`scenario_id == "writing"` 与 patch auto-apply  
- `turn_controller.py`：writing 系统提示特判  
- `generation.py`：writing / intel temperature 分支  
- `delegate_runner.py`：writing 默认子 agent  

设计上说「场景是配置」；实现上内核又认识 `"writing"` 这个名字。短期方便，长期每加场景都往内核塞 `if`，宪法失效。

类比：规章写「审批走工单」，执行上又口头特批绕过系统。

---

## 3. 效果锚未闭合

两层证明不要混：

| 层 | 作用 | 现状 |
|----|------|------|
| Golden / `make gate` | **行为**契约不坏 | 较强 |
| Official **主栏锚点** | live 上效果分数可对比 | `eval/official/baseline/SCORECARD.md` 主栏仍空 |

冒烟趋势可以有数，但文档自认冒烟**不作效果结论**。  
因此「Coding fuse / AST 已接线」是工程落地；还不能严谨地说「效果达到某门槛 / 比上周更好」——缺少被认可、写入主栏、可打 Δ 的锚点 run。

「未闭合」= 能力接上了，**效果账本还没落章**。
