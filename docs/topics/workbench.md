# 工作台（写作 · Ops Bench · 证明）

写作主路径、Ops 官方 Bench 效果温度计、契约切片与合入证明。

## 图

1. [写作主路径](../assets/writing/writing-main-path-zh.png) — Work 树 · 按需检索 · diff-first  
2. [Ops Bench 原理](../assets/ops/ops-bench-principle-zh.png) — L1 agent-path · 套件 · 隔离 · SCORECARD  

![写作主路径](../assets/writing/writing-main-path-zh.png)

![Ops Bench 原理](../assets/ops/ops-bench-principle-zh.png)

## 1. 写作：Work over Session

用户心智是「一本书 / 一份稿」；工程上 **Work** 拥有树，**Session** 只是对话线程。

```text
work_root/
  outline.md
  manuscript.md 或 sections/
  drafts/                 # 在编
  sources/                # 资料；cards/ 文风与设定卡
  .agent/work/            # 作品级元数据
```

同一账号默认一个 Work；多 Session 换聊天线，不换世界。

### 1.1 用户可见主路径

```text
意图
  →（可选）大纲工具
  → 成稿：按需 search_sources（少次）+ draft_section / propose_patch
  → 改稿：diff-first · 通常 0 搜
  →（可选）polish · export lint · verify
```

规则：

- **每个 pass = 用户显式 Turn**；平台不自动串成 polish pipeline。  
- 质量杠杆：稳定前缀 + 少次有 cite 的检索；**不是**资料越多越好。  
- **禁止默认**：每轮强制 RAG、Turn 末 judge、自动串联多模型裁判。

### 1.2 场景与工具（写作）

| 场景 | 主杠杆 | 是否检索 |
|------|--------|----------|
| 立人设 / 文风 | 卡 pin | 否 |
| 据材料新写 | RAG + cite + 卡 | 要（控制次数） |
| 局部改稿 | patch + 卡 | 通常跳过 |
| polish / 导出 | 样例与 lint | 否 |

写盘走 `propose_patch` → 用户批准 → apply；同 Turn 写盘可粘性免批。

### 1.3 Agent 工作台（对照）

| 项 | 行为 |
|----|------|
| 写入 | 偏好 `edit_file` / `write_file`（非写作 patch 主链） |
| 结构智能 | Locate / Impact / Verify 焊进工具结果（见「工具与上下文」图 3） |
| AST 旁路 | 状态条订阅索引进度；ready 前不做假 |
| 分发失败 | 界面展示准入 429、`start_timeout` / `runner_lost` 等可读文案 |

## 2. Ops 官方 Bench（重点）

路径：`/ops/<密钥>/official`。  
**效果温度计，不是合入门禁**；服从 R1–R5。

### 2.1 三层别搞混

| 层 | 是什么 | 挡合并？ |
|----|--------|----------|
| **Bench** | 官方小集效果：BEIR / C-MTEB / LongBench / SWE | **否** |
| **Golden** | 接口/契约切片 | 否 |
| **ci_proof** | unit + gate 完整证明 | **是** |

### 2.2 L1 agent-path（Ops 验收唯一路径）

分数必须来自 **产品 Session/Turn → AgentEngine → 真实工具**，禁止为刷分绕过 loop。

```text
/official 或 make *-agent
  → 创建官方 run
  → 拒非 agent 路径
  → retrieval / retrieval_zh / context / coding
       ├ 检索：多轮 search_sources → 评测侧 RRF → nDCG
       ├ 上下文：读 passage.md → 抽 Answer: → F1/EM
       └ 编码：真实 checkout + harness；无 resolve_rate 则 failed
  → 从 tool / turn 事件取结果 → 对照 SCORECARD
  → manifest ⊨ ops_run_manifest.schema.json
```

计分臂以 **free**（自然搜/读/改）为主。依赖 bench 库隔离；SWE resolve 另需 harness + Docker。`coding_skip_api` 默认关（空补丁只通管道，非验收）。

### 2.3 套件原理

| 套件 | 官方源 | Turn 里主要工具 | 主指标 |
|------|--------|-----------------|--------|
| **retrieval** | BEIR 小集 | `search_sources` | nDCG@10 等 |
| **retrieval_zh** | C-MTEB 小切 | 同上 | 同上（勿与 BEIR 混栏） |
| **context** | LongBench 小切 | `read_file` 等 | agent F1 / EM |
| **coding** | SWE-bench Lite | `edit_file` / `write_file` 等 | **resolve_rate**（harness）；patch_rate 仅辅助 |

Coding 结构探针（fuse / impact / checks）用于观测揉合是否在线，**不代替**官方 resolve。  
工作区 AST：评测套件默认 `workspace_index_wait_ready=true`（产品 Turn-first 不变）；与产品 RAG 面隔离。  
Harness 失败 / 无 `resolve_rate` → suite **failed**（契约 `ops_run_manifest.schema.json`）。

### 2.4 与产品面隔离

| 平面 | 谁写 |
|------|------|
| 用户资料（产品库） | 日常写作 / Agent |
| Ops BEIR / C-MTEB（bench 库） | L1 sync |
| 离线 retrieval-bench | 独立基准脚本 |

Bench **不得**为刷分改产品检索默认，也不得把 ops 语料焊进用户可见库。

### 2.5 旁路观测

| 入口 | 用途 |
|------|------|
| `/retrieval` | 单次召回漏斗诊断（勿与套件名 L1 混淆） |
| envelope / raw | 组窗与事件只读 |
| 容量 / 分发卡 | pull 队列、租约、TTFB 等 |

## 3. Golden：契约 / 接口切片

对现网 api→runtime 跑 Golden YAML，断言协议与主路径行为。  
证明「接口与 loop 没炸」，**不能**冒充生产效果；**不阻断合并**。

## 4. 完整证明（阻断合并）

同一脚本：Actions · 本地 `make ci-proof` · Ops `suite=ci`。  
顺序：stub bootstrap → unit → `make gate`（smoke + eval-all）。  
步骤图：[ci-proof-zh.png](../assets/ops/ci-proof-zh.png)。

| 旁路 | 含义 |
|------|------|
| `make preflight` | unit 快闸 ≠ 完整证明 |
| Ops Bench / golden | 效果或切片 ≠ 合入门禁 |

日常：`make smoke` · `make gate`；效果看 `/official` + SCORECARD。
