# 19 — Skills 层（可组合能力包）执行方案与去留判断

> **性质**：设计 + 开闸后薄实现（单篇维护；**勿另开 execution 文**）。  
> **问题**：是否要做「像 Cursor 那样默认预注入 ~1K 级 Skills 目录」的能力包层？  
> **约束继承**：[13-rate-redlines.md](13-rate-redlines.md) 速率红线 R1–R5；[10-product-experience.md](10-product-experience.md) TTFB / 首 token；[ADR-005](adr/005-agentic-loop-over-pipeline.md) / [ADR-006](adr/006-tool-centric-capabilities.md) / [ADR-014](adr/014-turn-intake-over-intent-pipeline.md)。  
> **现状基线**（2026-07）：Rules 合并在 Scenario `system.md`；能力靠 Profile `tool_names` + ToolRegistry；Web 明示「平台暂无独立 Skills 层」。  
> **本文结论（摘要）**：**近期末必做；默认不全量预注入 Skills。** 若未来做，只做「极瘦目录 + 按需加载」，且须先证明 system/tools 装不下的真实工作流。详见 §0 / §8。

---

## 0. 去留判断（先读）

### 0.1 一句话

Cursor 上下文里那截 ~1.2K Skills，本质是 **通用 IDE Agent 的「可选工作流目录」**（create-hook、canvas、sdk…），用来避免把几十份说明书塞进常驻 system。  
本平台当前是 **双场景窄产品**（writing / agent），程序性知识已大量写在 `system.md` + 工具 description 里——**再叠一层默认 Skills，边际收益低，却稳定占用每轮上下文并增加认知面。**

### 0.2 决策表

| 问题 | 判断 |
|------|------|
| 是否「有必要」对齐 Cursor 默认带 Skills？ | **否**。形态可参考，产品阶段不同，不必抄默认预注入 |
| 是否「值得」作为下一优先级（相对多模态 `21`、Harness 补洞）？ | **不值得抢排期** |
| Skills 这种机制本身有没有价值？ | **有**——当可选工作流变多、system 开始膨胀时，作为 **Context 面的渐进披露** |
| 现在要不要开工实现？ | **默认不开工（Defer）**；满足 §8 开闸条件再进 S0 |
| 若用户强需求「预注入」？ | 只允许 **≤800–1200 tokens 的 catalog 摘要**，禁止默认全文预注入 |

### 0.3 与「预注入」目标的对齐

| 你想要的 | Cursor 实际更接近 | 本平台建议 |
|----------|-------------------|------------|
| 默认上下文里就有 Skills | **目录（name+description）** 常驻，**正文按需** | 若做：同构；**不做全文预注入** |
| 用户没写也能有 | 内置 `skills-cursor` 打包进产品 | 内置 builtin 可以，但 **当前场景清单撑不满必要性** |
| 可组合能力包 | 个人 / 项目 / 内置多层 | 延期到 workspace 扩展需求明确时 |

---

## 1. 需求对照（若未来做）

| # | 视角 | 要求 | 落点 |
|---|------|------|------|
| 1 | **交互速率** | 不挡 TTFB；不在首 token 前加模型调用；catalog 组装 ≤ 毫秒级 | R1–R3；硬顶 `skills_catalog_max_tokens` |
| 2 | **场景需要** | writing / agent 各自只挂「该场景真用到的」条目 | Profile `skill_ids` 子集；禁止两场景共用大杂烩目录 |
| 3 | **成熟做法** | 目录发现 + 渐进披露；Skills ≠ 新 tools 通道 | `load_skill` 工具或等价只读；loop 不变 |
| 4 | **可证明** | 有 golden：加载后行为变化；有预算断言 | `12` 风格 stub golden |

**验收一句话（仅开闸后）**：默认 Turn 的 catalog ≤ 预算；简单任务零 `load_skill`；复杂专项任务可加载正文且不拖慢 `turn.accepted`。

---

## 2. 速率影响分析（R1–R5）

### 2.1 预注入什么，成本差在哪

```text
方案 A：每轮注入全部 SKILL.md 正文     → 数千～数万 token，首 token/费用双杀   ❌ 否决
方案 B：每轮注入 name+description 目录 → ~0.5–1.5K token，CPU 可忽略           ⚠ 有成本，须证明值得
方案 C：目录也不注，仅工具/系统里写清   → 0 额外 token（现状）                   ✅ 当前默认
方案 D：B + 模型按需 load_skill 全文   → 目录常驻小额 + 正文按需                ✅ 唯一可接受的「有 Skills 层」
```

| 红线 | Skills 含义 |
|------|-------------|
| **R1** | Catalog 在 ContxtEngine 同步拼字符串；禁止为选 Skill 调 LLM |
| **R2** | 禁止「先开小模型路由再进主 loop」 |
| **R3** | 扫磁盘限 builtin + 可选 workspace 少量文件；结果 **进程内缓存**（按 scenario） |
| **R4** | Skill 内脚本/重 I/O 不得在 assemble 同步跑 |
| **R5** | `skills_catalog_tokens` 进 `context.reported`；超预算裁剪可测 |

### 2.2 对交互体感的具体影响

| 项 | 影响 |
|----|------|
| TTFB | 方案 B/D 若实现正确：**可忽略**（纯内存拼接） |
| 首 token / 输入费用 | 每轮多 ~1K input → **所有 Turn 恒定税**；长会话放大账单 |
| 多一轮 tool | `load_skill` 可能 **+1 step**；简单改稿被诱去加载则变慢（需 system 写明「简单任务勿加载」） |
| Cancel | 无新增难取消点（仍在同一 loop） |

**速率结论**：Skills 层的主成本不是延迟，而是 **每轮上下文税 + 可能多一步**。在双场景已有厚 system 时，这笔税不划算。

---

## 3. 场景是否需要（writing / agent）

### 3.1 写作模式（writing）

| 已有承载 | 位置 |
|----------|------|
| 卡片优先级、检索何时用/跳过、引用工作流、export 约束、plan 弱提示 | `scenarios/writing/system.md` |
| `search_sources` / `draft_section` / `propose_patch` / `update_plan` / … | `writing.yaml` tool_names |

**痛点是否像「缺 Skills」？**  
当前更像是：**流程已写在 Rules（system）里**。再拆 Skills，容易变成同一套 citation/export 说明的第二份拷贝，模型两处看到重复指令，收益低。

**何种写作痛点才值得 Skills？**（开闸信号）

- system.md 明显超长（例如持续 >X 行且多段互斥流程互相干扰）
- 出现 **可选、低频** 流程（如「剧本格式交稿」「学术引用 GB/T」），不应常驻每个改错别字的 Turn
- 用户/工作区需要 **自带** 交稿规范包（workspace skills）

### 3.2 Agent 模式（agent）

| 已有承载 | 位置 |
|----------|------|
| 探索纪律、规划可选、交付约束 | `scenarios/agent/system.md` |
| 读写改、检索、shell、delegate、lints… | `agent.yaml` tool_names |

**对比 Cursor**：Cursor Agent 面对「整个 IDE 产品能力面」（hooks、PR、canvas、迁移…），目录价值高。  
本平台 Agent 是 **沙箱内编码助手**，能力面已被 Profile **显式裁剪**，没有「二十个互不相关的产品工作流」要发现。

**开闸信号**：工具很多但 **使用剧本** 装不进 system；或要支持第三方/工作区贡献的「操作手册」而不改镜像。

### 3.3 场景结论

| 场景 | 近期末做 Skills 的理由 | 将来可做的形态 |
|------|------------------------|----------------|
| writing | system 已覆盖主路径 | 低频交稿/文体包 → workspace 或可选 catalog |
| agent | 工具集闭环，无 IDE 级工作流膨胀 | 委派剧本、复杂 verify 手册 → 按需 load |

---

## 4. 成熟 Agent 怎么用 Skills（参照，不照搬）

### 4.1 Cursor 类（Skills 作为产品概念）

观察与公开技能规范一致的做法：

1. **Description 进发现面**（常驻或可发现列表）——对应你看到的 ~1.2K  
2. **SKILL.md 正文渐进披露**——相关时再读，默认不灌全文  
3. **Skills ≠ tools**：Skill 教步骤；执行仍靠已有工具（读文件、跑命令、改设置）  
4. **内置 + 用户/项目** 多层来源；用户零配置也有内置目录  

适用前提：**可选工作流数量 ≫ 适合写进一份 system 的量**。

### 4.2 Claude Code / 本仓库同构派

- 内核仍是 **agentic loop + tools**  
- 「专项知识」更多在 **CLAUDE.md / system / 项目约定** 或 **按需读仓库内 md**  
- 不一定产品化名叫 Skills，但 **「别把一切常驻」** 的原则一致  

### 4.3 对本平台的启示

```text
值得学：两级披露、预算、不改 loop、不靠 LLM 路由
不必学：在窄双场景上强行默认 1.2K 目录「看起来像 Cursor」
```

---

## 5. 若开闸：目标架构（薄实现）

### 5.1 包格式

```text
skills/<id>/
  SKILL.md           # YAML: name, description；正文步骤
  reference.md       # 可选
  scripts/           # 可选；禁止 assemble 期执行
```

来源优先级（高 → 低覆盖同名）：`workspace` → `scenario` → `builtin`（可配置）。

### 5.2 上下文形态

```text
system（Rules，已有）
[+ 极瘦 skills_catalog 块]     ← 仅开闸后；硬顶
tools=（已有）+ load_skill      ← 正文只经工具回灌
messages / runtime（已有）
```

`load_skill(name)`：返回 SKILL 正文（截断硬顶，如 ≤4K chars）；写 `skill.loaded` 事件（可选）。

### 5.3 Profile 挂载

```yaml
# writing.yaml / agent.yaml（示意）
skill_ids: []          # 默认空 = 不注入目录（推荐现状）
# skill_ids: [cite-workflow]  # 显式开启才预注入目录条目
```

**默认空列表**：保持今日行为；避免「做了层就强制税」。

### 5.4 明确非目标

| 否决 | 原因 |
|------|------|
| 每轮全文预注入所有 Skills | 速率与费用红线 |
| LLM / 意图节点选 Skill | ADR-014 |
| Skill 内注册新工具绕过 Registry | ADR-006 |
| 为 Skills 加固定 pipeline 节点 | ADR-005 |
| 为「对齐 Cursor UI」硬加 1.2K 空目录 | 无场景清单则纯税 |

---

## 6. 与现有机制的边界

| 机制 | 职责 | Skills 介入？ |
|------|------|----------------|
| Rules（`system.md`） | 常驻约束、主路径流程 | 主路径继续放这里 |
| Tools | 可调用接口 | Skill 只 **引用** 工具名 |
| `plan_hint` | 多目标弱提示 | 不升级为 Skill 路由 |
| RAG 工具 | 按需资料 | 不改为 Skill 替代检索 |
| Project（`AGENT.md`） | 工作区约定 | 可与 workspace skills 并存，避免重复 |

Web `UsageMeter` 文案：开闸后改为显示 `skills_catalog` token；未开闸保持「暂无独立 Skills 层」。

---

## 7. 分期（仅开闸后执行）

| 期 | 内容 | 速率门槛 |
|----|------|----------|
| **S0** | 包格式 + Registry + **默认 `skill_ids: []`** + 单测解析 | 无行为变化 |
| **S1** | 单场景 1～2 个真实 Skill + catalog 注入 + `load_skill` + golden | catalog ≤1200 tok；简单任务 0 load |
| **S2** | workspace `.agent/skills/` + Web 展示 | 扫描缓存；失败降级为空目录 |
| **S3** | 运营/热更新（非必须） | 不进 Turn 热路径同步拉取 |

依赖：

```text
先满足 §8 开闸 → S0 → S1（有真实剧本）→ 可选 S2
禁止：无开闸证据直接做「默认全场景 1.2K 目录」
```

---

## 8. 开闸条件 / 否决条件

### 8.1 开闸（需同时满足）

1. **清单**：至少 **3** 个互不重复、且不适合再塞进对应 `system.md` 的工作流（写作或 agent 分开数）。  
2. **证据**：system 或工具 description 已出现「过长 / 互相抢注意力」的可观测问题（空转、漏步骤、黄金失败归因于指令拥挤）。  
3. **速率设计**：catalog 预算与 `load_skill` 截断数字写进 PR 描述，并有 `context.reported` 字段。  
4. **优先级**：不与更高价值项抢（当前文档栈上多模态 [`21`](18-multimodal-design.md)、Harness 补洞更优先）。

### 8.2 明确否决（当前）

| 动机 | 为何否决 |
|------|----------|
| 「Cursor 有，我们也要默认 1.2K」 | 产品面宽度不同；属外观对齐 |
| 「先做层再找内容」 | 违反可证明；易变成空税 |
| 「用 Skills 做意图分类 / 场景路由」 | 违 ADR-014 / 013 |
| 「Skills 代替 RAG / 代替工具」 | 机制错位 |

### 8.3 当前推荐动作

| 动作 | 说明 |
|------|------|
| **保持现状** | Rules + Tools；UsageMeter 文案可保留 |
| **短期改进（若要提升「专项能力」）** | 加厚/拆分 `system.md` 段落；优化工具 description；必要时 `read_file` 工作区手册 |
| **本文归档为设计库存** | 开闸后再按 §7 拆 PR；宜补 ADR-02x「Skills 为 Context 渐进披露，非编排层」 |

---

## 9. 风险登记

| 风险 | 缓解 |
|------|------|
| 每轮 1K 税无感但积少成多 | 默认 `skill_ids: []`；预算硬顶 |
| 模型乱 `load_skill` 多一轮 | system 写清触发条件；golden 覆盖「简单任务不加载」 |
| Skill 与 system 双源冲突 | Skill 只承载 **可选低频** 流程；主路径不搬 |
| 与 Cursor Skills 格式纠缠 | 可兼容目录布局，**不**承诺 IDE 技能热同步 |

---

## 10. 文档与关联

| 文档 | 关系 |
|------|------|
| [`06-tools-and-context.md`](06-tools-and-context.md) | 工具与上下文分区；Skills 若落地挂 Context 面 |
| [`09-product-modes.md`](09-product-modes.md) | ScenarioProfile 扩展点 |
| [`12-model-harness.md`](12-model-harness.md) | Harness 厚度 ≠ 加 Skills 层充数 |
| [`13-rate-redlines.md`](13-rate-redlines.md) | R1–R5 |
| [`18-multimodal-design.md`](18-multimodal-design.md) | 更高优先级设计稿对照 |

---

## 11. 总结

| 角度 | 结论 |
|------|------|
| **交互速率** | 目录预注入主要是 **token 税**；全文预注入不可接受；实现正确则几乎不影响 TTFB |
| **场景需要** | writing / agent **当前不缺** Skills 层；缺的是把主路径写在 system/tools 里（已做） |
| **成熟做法** | 学渐进披露，不学「窄产品也默认 1.2K」 |
| **是否值得现在做** | **不值得作为现行排期**；机制可保留为开闸后方案 |
| **预注入目标** | 若坚持「像 Cursor」，只注入 **瘦目录**，且 **默认关闭**，有清单再按场景打开 |

**最终口径**：Skills 是可选的 Context 渐进披露能力，**不是**当前双场景的必需品；在开闸条件满足前，**不做预注入 Skills 层**。
