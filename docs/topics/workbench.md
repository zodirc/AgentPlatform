# 工作台（写作 · Ops Bench · 合入证明）

写作主路径、Ops 官方 Bench（效果温度计）、契约切片、合入证明。后三层**不要混读**：

| 层 | 是什么 | 挡合并？ |
|----|--------|----------|
| **Ops Bench** | 官方小集效果：BEIR / C-MTEB / LongBench / SWE | **否** |
| **Golden** | 接口/契约切片 | 否 |
| **ci_proof** | unit + gate 完整证明 | **是** |

Ops 控制台的 `suite=ci` 只是触发 `scripts/ci_proof.sh`，不是 retrieval/coding 那些效果套件。

## 图

1. [写作主路径](../assets/writing/writing-main-path-zh.png) — Work 树 · 按需检索 · diff-first  
2. [Ops Bench 原理](../assets/ops/ops-bench-principle-zh.png) — L1 agent-path · 套件 · 隔离  
3. [评测原理](ops-eval-principles.md) — 题目、命中、harness、审阅偏差  
4. [实例走查](ops-eval-walkthrough.md) — 本地题目原文与命中判定  
5. [图 · 检索实例](../assets/ops/ops-eval-walk-retrieval-zh.png) — SciFact q-3 / q-1  
6. [图 · 上下文实例](../assets/ops/ops-eval-walk-context-zh.png) — LongBench idx 0 / 1 / 2  
7. [图 · 编码实例](../assets/ops/ops-eval-walk-coding-zh.png) — 14365 / 12907 · harness  
8. [分数入账](../assets/ops/score-snapshot-zh.png) — `latest_*` → RESULTS vs SCORECARD 主栏  
9. [检索一题计分](../assets/ops/ops-retrieval-score-zh.png) — 评测侧多轮 RRF · BEIR≠C-MTEB  
10. [上下文一题计分](../assets/ops/ops-context-score-zh.png) — 抽 `Answer:` · F1/EM  
11. [编码一题计分](../assets/ops/ops-coding-score-zh.png) — 探针 ≠ harness `resolve_rate`  
12. [CI 证明](../assets/ops/ci-proof-zh.png) — 合入门禁（与效果套件不是同一条链）

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

用户心智是「一个仓库 / 一道题」；工程上仍是同一 Work → Session → Turn。

用户把题（或仓库里的 `problem.md`）发进来。模型先读题、用 issue 里的最小例子复现坏现象，再用 `search_codebase` 找定义、打开文件、`edit_file` 就地改。改成功时结果里已经带着：这段大概影响谁、这次写入的诊断、以及一条可复制的相关测试命令。官方评测 Turn 会在解题环境里代跑那一个邻近测试文件，失败首条焊进 `related_tests_run`；产品工作台仍不代跑。然后模型自己看邻文件诊断，再用同一条复现命令验一遍。

若它这时不再点工具、直接交卷，平台还要看两件事：改过代码之后有没有跑过测试；仓库测试绿了之后，issue 正文里的例子有没有在**最新一次编辑之后**再跑过。缺哪条就往对话里塞一条用户口吻的提醒，再给一轮，而不是默默收下终稿。磁盘上最终留下补丁或回答。

写盘偏好 `edit_file` / `write_file`（不是写作那条 patch 主链）。找定义、看波及、改完再验都焊进这些工具的返回值，不另加导航工具名。界面上的符号表进度条只报告扫到哪了，ready 之前不得画成已经能精确定位。官方编码评测题会把 pytest/`|tail` 改去该题 Docker 镜像里跑，并禁止在裸源码树上 pip。分发失败时界面展示准入 429、无人领取超时、租约丢失等可读文案。

细则：[工具与上下文 §2](../core/tools-and-context.md) · [Runtime](../core/runtime.md)。

## 2. Ops 官方 Bench（效果，不是 CI）

路径：`/ops/<密钥>/official`。  
**效果温度计，不是合入门禁**；服从架构文里的速率红线（不挡受理、首 token 前不加同步模型、重活异步、可测才合并）。给了什么题、什么叫命中、harness 干什么：见 [评测原理](ops-eval-principles.md)。分数如何从一次跑写进 `RESULTS.md` / 能否升 SCORECARD 主栏，见 [分数入账图](../assets/ops/score-snapshot-zh.png)。

文首三层表已说明 Bench ≠ Golden ≠ ci_proof。本节只讲 Bench。

### 2.1 L1 agent-path（Ops 验收唯一路径）

分数必须来自 **产品 Session/Turn → AgentEngine → 真实工具**，禁止为刷分绕过 loop。

```text
/official 或 make *-agent
  → 创建官方 run
  → 拒非 agent 路径
  → retrieval / retrieval_zh / context / coding
       ├ 检索：多轮 search_sources → 评测侧 RRF → nDCG
       ├ 上下文：读 passage.md → 抽 Answer: → F1/EM
       └ 编码：真实 checkout + 测在该题 Docker 镜像里跑 + 官方 harness；没有通过率则 failed
  → 从事件取结果 → 对照 SCORECARD（主栏仍空时看 RESULTS.md）
  → 评测清单须满足契约（coding 无 resolve 不得 completed）
```

计分臂以 **free**（自然搜/读/改）为主。依赖 bench 库隔离；SWE resolve 另需 harness + Docker。`coding_skip_api` 默认关（空补丁只通管道，非验收）。

### 2.2 套件原理

命中定义与审阅偏差以 [评测原理](ops-eval-principles.md) 为准。下表只记「谁出题 / 主工具 / 主指标」。

| 套件 | 官方源 | Turn 里主要工具 | 主指标（命中） |
|------|--------|-----------------|----------------|
| **retrieval** | BEIR 小集 | `search_sources` | 排序里的 `doc_id` ∈ qrels；nDCG / **R@100** / MAP |
| **retrieval_zh** | C-MTEB 小切 | 同上 | 同上（勿与 BEIR 混栏） |
| **context** | LongBench 小切 | `read_file` 等 | 抽 `Answer:` 后 F1 / EM（v2 不做子串 EM） |
| **coding** | SWE-bench Lite | `edit_file` / `write_file` 等 | **harness**：F2P 全过且 P2P 全过；patch_rate 仅辅助 |

找定义是否揉合成功、改完有没有回灌失败摘要、想收工时有没有再催一轮——这些探针只观测平台是否在线，**不代替**官方是否判这题通过。  
工作区符号表：评测套件默认等索引 ready；产品 Turn 仍先受理。与产品资料检索面隔离。  
解题侧：pytest/`|tail` 改去该题 Docker 镜像跑完整测试（复用容器）；issue 正文里的例子必须在最新编辑后再跑过，且不得把官方隐藏测试泄漏给模型。  
Harness 失败或没有通过率 → 套件 **failed**，不得标 completed 粉饰成模型零分。  
现行冒烟：[`RESULTS.md`](../../eval/official/baseline/RESULTS.md)（第4–5轮 coding 4/5，未升主栏）。

### 2.3 与产品面隔离

| 平面 | 谁写 |
|------|------|
| 用户资料（产品库） | 日常写作 / Agent |
| Ops BEIR / C-MTEB（bench 库） | L1 sync |
| 离线 retrieval-bench | 独立基准脚本 |

Bench **不得**为刷分改产品检索默认，也不得把 ops 语料焊进用户可见库。

### 2.4 旁路观测

| 入口 | 用途 |
|------|------|
| `/retrieval` | 单次召回漏斗诊断（勿与套件名 L1 混淆） |
| envelope / raw | 组窗与事件只读 |
| 容量 / 分发卡 | 领取队列、租约、首 token 到达时刻等 |

## 3. Golden：契约 / 接口切片

对现网 api→runtime 跑 Golden YAML，断言协议与主路径行为。  
证明「接口与 loop 没炸」，**不能**冒充生产效果；**不阻断合并**。

## 4. 完整证明（阻断合并）

这是 **CI**，不是 Ops 效果跑分。同一脚本：GitHub Actions · 本地 `make ci-proof` · Ops 控制台 **`suite=ci`**（仅触发器，不是 official 四套件之一）。  
顺序：stub bootstrap → unit → `make gate`（smoke + eval-all）。  
步骤图：[ci-proof-zh.png](../assets/ops/ci-proof-zh.png)。

| 旁路 | 含义 |
|------|------|
| `make preflight` | unit 快闸 ≠ 完整证明 |
| Ops Bench / golden | 效果或切片 ≠ 合入门禁 |

日常：`make smoke` · `make gate`；效果看 `/official` + [`RESULTS.md`](../../eval/official/baseline/RESULTS.md)（SCORECARD 主栏仍空时不要读机器栏当最新）。
