# 28 — Proof 门禁与体验信号（环外优化）

> **状态：PX0 / PX1（含 PX1d）/ PX2a–b 已落地** · 2026-07-23  
> 前置：[`11-eval-and-golden-turns`](11-eval-and-golden-turns.md) · [`13-rate-redlines`](13-rate-redlines.md) · [`10-product-experience`](10-product-experience.md) · [`12-model-harness`](12-model-harness.md) · [`14-writing-quality`](14-writing-quality.md)  
> **产品意图（硬）：**  
> 1. **不影响** Agent 交互速率与 Agent 交互逻辑  
> 2. **对齐** 成熟 Agent：主环只保证跟手 / 可控 / 可审；「变差了没」放在环外证明  

本文 **不是** 质量 judge 进热路径，也 **不是** 再开一套 `*-execution` 平行文。  
变更只改本文票状态；细节契约仍以 `11` / `08` / `14` 为准。

### 落地索引（2026-07-23）

| 项 | 落点 |
|----|------|
| **Ops 完整证明 / `make ci-proof`** | 与 CI 同脚本 `scripts/ci_proof.sh`：unit → gate（smoke+eval-all；不重复 runtime pytest） |
| Ops Golden 切片 | [29](29-ops-eval-console.md) `suite=golden`；**切片绿 ≠ 合并证明** |
| Ops `skipped` | 仅 golden；环境耦合命令 skipped（≠ fail）；全量由 suite=ci / gate 覆盖 |
| CI / nightly | `.github/workflows/ci.yml` · `nightly.yml` |
| 体验信号核心 | `packages/contracts/python/agent_contracts/ux_signals.py` |
| 体验信号 CLI | `scripts/ux_signals.py` · `make ux-signals` |
| 体验信号 API | `GET /api/v1/admin/ux-signals`（用户触发只读） |
| 体验信号 Web | 设置 → `/settings/signals` |
| PX2 结构提醒 | `structureHints.ts` → `PatchDiffPanel`（仅 UI，默认开；`showStructureHints={false}` 可关） |

---

## 0. 一句话

在 **冻结 loop、服从 R1–R5** 的前提下，用两条环外能力补齐成熟度：

1. **强制 Proof 门禁**（CI / 本地闸）：改 Prompt / 工具 / Intake 时行为退化可发现  
2. **用户体验信号**（事件派生指标 + 告警）：真实「拒稿 / 短窗再改 / 取消」捕到离线 rubric 捕不到的变差  

第三条（写入前语义轻校验）**降级为可选 UX 旁路**，且 **禁止回灌模型 messages**。

---

## 1. 问题陈述（校准后）

外部意见常被说成「没 Golden / 事后标脏不够 / 缺重写率」。对照本仓库现状，校准如下：

| 外部说法 | 校准后的真缺口 |
|----------|----------------|
| 「改 Prompt 靠感觉」 | Golden / `make eval-*` **已有**；缺的是 **强制门禁**（docs/11 写明已移除 GitHub Actions；`04` 仍列 `ci.yml` 但仓库无 workflows） |
| 「事后标脏不够早」 | 现有标脏是 **cite 证据纪律**（`_annotate_unverified_citations`），不是文风语义；另有 `export_lint`（导出时）。缺的若有，也只是 **用户可见、模型不可见** 的结构提醒，不是写前语义闸 |
| 「缺重写/撤销率」 | 事件原料已有（`patch.*` / cancel / Turn 终态）；缺 **聚合指标 + 阈值告警** |

**成熟 Agent 分法：**

```text
主环（用户等待路径）     环外（Proof / 观测）
─────────────────     ──────────────────
跟手 · 可打断 · diff    CI Golden · 体验信号 · 离线 rubric
不塞 judge / 不塞质检阶段
```

---

## 2. 两条硬门槛（本文宪法）

> 任一轨提案若触碰下列红线，直接否决。

### 2.1 不影响 Agent 速率（R1–R5）

| 红线 | 对本方案的含义 |
|------|----------------|
| **R1** | 门禁与指标 **不得** 推迟 `turn.accepted` |
| **R2** | **禁止**为质量 / 建议 / 告警在热路径同步调模型 |
| **R3** | 若做内容规则扫描：仅毫秒级正则/结构；重活异步 |
| **R4** | CI、rubric、日聚合、告警 → 异步 / 离线 / 运维面 |
| **R5** | 每轨可测：workflow 可复现；指标有定义与单测夹具 |

### 2.2 不影响 Agent 交互逻辑

**冻结（三轨落地时也零改动）：**

| 冻结项 | 说明 |
|--------|------|
| `AgentEngine` while | 不增质检节点、不改 assemble→model→tools 顺序 |
| Scenario 宪法 | 不在引擎内 `if scenario` 分支业务 |
| 工具成败语义 | 规则提醒 **不得** 把成功写成失败，**不得** 阻断 `propose_patch` / `draft_section` / `write_file` |
| 模型可见上下文 | 可选 lint **不得** 默认写入 `messages` / `tool_result` 正文（见 §5） |
| Plan / 同意门 / ToolScope | 不因本方案放宽或收紧 |

**允许改的（仅环外 / 观测 / UI 投影）：**

| 允许面 | 说明 |
|--------|------|
| CI / Makefile / docs/11 触发口径 | 恢复「每 PR 阻断」与 nightly |
| 事件派生聚合表 / metrics / 告警 | 只读 `turn_events` 或投影字段 |
| Web 侧栏 / diff 旁 warnings | 只给用户看，不进模型窗 |

---

## 3. 总优先级

```text
PX0  Proof 门禁（CI + 本地闸）     ← 零交互成本 · 防静默退化
PX1  体验信号（拒/再改/取消）      ← 零交互成本 · 真质量传感器
PX2  可选：UX-only 结构提醒       ← 仅用户可见；默认可不做
```

与 Harness 六面：本方案加厚 **Proof** 与产品观测；**不**加厚热路径 Model/Tools 语义。

---

## 4. PX0 — Proof 门禁（强制回归）

### 4.1 目标

让「改 `system.md` / 工具白名单 / Intake / 契约」在合并前 **必须** 经过已有 Golden 分层，而不是靠自觉跑 `make eval-all`。

### 4.2 非目标

- 不重写 Golden 体系（权威仍是 [`11`](11-eval-and-golden-turns.md)）  
- 不把 live 质量闸塞进每 PR（L2 仍 nightly 告警）  
- 不在用户 Turn 内跑 eval  

### 4.3 现状与缺口

| 已有 | 缺口 |
|------|------|
| `make smoke` / `eval-all` / `eval-retrieval` / `eval-queue` / `runtime-test` | 无 `.github/workflows/`；门禁靠文档与记忆 |
| docs/11 §4 写明 L0/L1「每 PR 阻断」 | 与「已移除 GitHub Actions」自相矛盾 |
| docs/04 目录仍列 `ci.yml` | 文件不存在 → 文档漂移 |

### 4.4 设计

```text
PR / 合并前
  ├─ L0  make smoke          （或等价 compose health + 1 stub）
  ├─ L1  make eval-all       （stub Golden；isolated + runtime-lite）
  ├─ 单测 make runtime-test（及改动触及的 api-test）
  └─ （可选门）改 retrieval/queue 相关路径时跑 eval-retrieval / eval-queue

Nightly（不阻断合并）
  ├─ L2  make eval-live（样本；漂移告警）
  └─ 可选 L3 负载 / SSE 重连
```

**实现落点（建议）：**

| 项 | 落点 |
|----|------|
| Workflow | `.github/workflows/ci.yml`（恢复；与 `04` 对齐） |
| 本地 / CI | **Ops `suite=ci` / `make ci-proof`** ≡ GitHub Actions；`make gate` 为 docker 半边 |
| 文档 | 修订 `11` §4：删除「已移除 CI」；改为「CI + 本地 `make gate`」 |
| Prompt 敏感 | 约定：改 `scenarios/*/system.md`、writing cards、工具 bootstrap → PR 描述勾选已跑 `make gate`；后续可加 path filter |

### 4.5 票

| 票 | 内容 | 验收 | 状态 |
|----|------|------|------|
| **PX0a** | 新增 `make gate`；文档入口写清 | 本地一条命令复现 L0+L1+单测 | ✅ |
| **PX0b** | 恢复 `.github/workflows/ci.yml`（L0+L1 阻断） | PR 红绿与 docs/11 §4 一致 | ✅ |
| **PX0c** | 修订 `11` §4 / `04` 目录漂移；nightly 骨架（L2 告警） | 文档与仓库一致；nightly 可空跑 | ✅ |
| **PX0d** | （可选）Prompt/工具 path 的 CI 注释或 required check 说明 | 贡献者知何时加跑 retrieval/queue | ✅ 注释 |

**速率 / 逻辑影响：** 无（纯工程门禁）。

---

## 5. PX1 — 用户体验信号（拒稿 / 再改 / 取消）

### 5.1 目标

用 **已发生的用户行为** 做质量传感器：某日拒稿率或短窗再改率相对基线异常升高 → 告警。  
**不**把信号反馈进 loop（不做自动改 Prompt、不自动拦 Turn）。

### 5.2 非目标

- 不做 IDE 级 undo 栈（写作「撤销」代理 = `patch.rejected` + 短窗再 Turn）  
- 不做热路径同步打分  
- 不替代 Golden（互补：契约 vs 体感）  

### 5.3 指标定义（v1）

均从 `turn_events`（及必要投影）**日聚合**；按 `scenario_id`、可选 `work_id` 切片。

| 指标 | 定义（v1） | 说明 |
|------|------------|------|
| **RejectRate** | `patch.rejected / (patch.applied + patch.rejected)` | 写作主信号；分母为 0 则跳过 |
| **ReeditRate** | 同 `work_id`（或同 section 路径）在 ΔT 内再次出现成功写工具的 Turn 占比 | ΔT 默认 30min；「重写」代理 |
| **CancelRate** | `turn.cancelled / turn.completed+cancelled+failed` | 跟手/可控异常时会抖 |
| **ProposeAbandon** | 提出 `patch.proposed` 后 Turn 结束且无 applied/rejected | 可选；观察「看了没动手」 |

**告警（v1）：** 相对过去 7 日同 scenario 中位数，**RejectRate 或 ReeditRate ≥ 2×** 且当日样本 ≥ N（建议 N=20）→ 告警。阈值进配置，不进引擎。

### 5.4 设计

```text
turn_events（事实源）
  → 旁路 job / 定时 SQL 或 scripts/ux_signals_aggregate.py
  → ux_signal_daily（表或 metrics 导出）
  → 告警通道（日志 + 可选 webhook）；Web 只读仪表可后置
```

| 约束 | 做法 |
|------|------|
| R1–R4 | 聚合 **永不** 挂在 StartTurn / SSE 热路径；outbox 或 cron |
| 隐私 | 只存计数与比率；不存正文 |
| 多租户 | 默认按当前租户/Work 隔离聚合；全局运维视图需显式角色 |

### 5.5 票

| 票 | 内容 | 验收 | 状态 |
|----|------|------|------|
| **PX1a** | 指标字典入库（本文 §5.3）+ 从事件抽数的脚本/SQL | 夹具事件可算出三率 | ✅ |
| **PX1b** | 日聚合落点（表或 Prometheus recording） | `make` 或 job 可跑；不影响 compose 热路径 | ✅ 报告 JSON |
| **PX1c** | 阈值告警（2× 中位数 + 最小样本） | 人为注入夹具可触发告警日志 | ✅ |
| **PX1d** | （可选）Web 只读「体验信号」页 | 只读；失败不挡写作 | ✅ `/settings/signals` |

**速率 / 逻辑影响：** 无（纯观测）。

---

## 6. PX2 — 可选：UX-only 结构提醒（降级轨）

### 6.1 定位

**已落地（UI 旁路）。** 确定性结构提醒只出现在 `PatchDiffPanel`；**不**回灌 messages / **不**改工具成败。

成熟 Agent 对照：靠 **diff + 拒收**；结构 lint 放侧栏，**不**在每次写入前教模型。

### 6.2 若做，必须满足

| 必须 | 禁止 |
|------|------|
| 确定性规则（扩展 `export_lint` 一类） | 同步 LLM / embedding「语义合理性」 |
| 只进 **projection / Web 侧栏 / diff 旁** | 默认写入 `messages` 或改写 `tool_result.summary` 给模型 |
| 不阻断 apply / write | 把成功标成失败、要求审批升级 |
| 挂点：`draft_section` / `propose_patch` 的 UI 面 | 只盯 `write_file` 或塞进 Engine 新阶段 |

规则示例（结构，非文风）：空段、标题层级跳跃、明显占位符（`TODO`/`TBD`/`xxx`）、未核验 cite 角标（复用已有 `citation_check` 字段到 UI）。

### 6.3 票

| 票 | 内容 | 验收 | 状态 |
|----|------|------|------|
| **PX2a** | 设计评审：确认「模型不可见」边界 | 书面否决回灌 messages | ✅ 仅 UI |
| **PX2b** | UI 旁路 warnings + 单测 | 关掉 UI 后行为与今日 bit-identical | ✅ `showStructureHints` |

---

## 7. 否决清单（写进评审口令）

| 提案 | 否决理由 |
|------|----------|
| Turn 末强制 LLM judge | R2 / R4；docs/14 已否决 |
| 写前语义 NLI / 小模型分类 | R2 / R3；改交互逻辑风险 |
| 规则 warnings 回灌 messages「让模型自己改」 | 改交互逻辑；易抖、难 golden |
| 用体验信号自动改 Prompt / 自动 Cancel | 闭环失控；成熟产品先告警后人介入 |
| 为门禁在用户 compose 默认栈跑 live eval | 污染日常 `MODEL_MODE=live`；应用 isolated（现有 eval-all 已隔离） |
| 恢复固定质检 pipeline 节点 | 违 ADR-005 |

---

## 8. 与现有模块的边界

| 模块 | 关系 |
|------|------|
| [`11`](11-eval-and-golden-turns.md) | PX0 **执行** 其 §4 分层；本文不另起 Golden 格式 |
| [`12`](12-model-harness.md) | 加厚 Proof 面；热路径成本清单不因本方案增加常驻项 |
| [`14`](14-writing-quality.md) | 离线 rubric / export_lint 保持；PX2 若做则复用结构规则，不替代 WQ |
| [`08`](08-event-projection-pipeline.md) | PX1 只读事件；可不改投影，或仅增只读聚合 |
| [`27`](27-multi-tenancy.md) | 聚合默认租户隔离；告警视图权限另定 |
| [`26`](26-plan-suggest-complexity.md) | 同宪法（环外、不改同意门）；本方案不碰 Plan 建议 |

---

## 9. 验收总表

| 轨 | 完成定义 |
|----|----------|
| **PX0** | PR 上 L0+L1 红绿可见；`make gate` 文档化；`11`/`04` 与仓库一致 — **✅ 2026-07-23** |
| **PX1** | 日维度三率可算；2× 告警可演示；热路径无新增同步逻辑 — **✅ CLI + API + `/settings/signals`** |
| **PX2** | UI 结构提醒；关闭后引擎行为 bit-identical — **✅ 默认 UI 旁路** |

**交互回归（三轨共性）：**

- `make smoke` · `make eval-all` 不因本方案变红  
- TTFB / 首 token SLO 口径不变（[`10`](10-product-experience.md)）  
- 引擎内无新增「质检」分支  

---

## 10. 建议落地顺序

```text
Week A   PX0a → PX0b → PX0c     ✅
Week B   PX1a → PX1b → PX1c     ✅
Backlog  PX0d · PX1d · PX2*     ✅（2026-07-23）
```

---

## 11. 相关

- 速率：[`13`](13-rate-redlines.md)  
- Eval：[`11`](11-eval-and-golden-turns.md) · [`eval/README.md`](../eval/README.md)  
- 体验 SLO：[`10`](10-product-experience.md)  
- Harness Proof：[`12`](12-model-harness.md)  
- 写作质量否决：[`14`](14-writing-quality.md) §1  
