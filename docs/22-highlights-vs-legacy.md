# 22 — 新平台相对旧项目：全景说明、结构优势与体感

> **本文定位**：一份**自洽、可脱离代码仓库阅读**的总说明。  
> **用途**：  
> 1. 上传到**独立文档仓库**供人阅读；  
> 2. 交给**其他 AI**做架构/产品/简历叙事分析时作为**唯一事实来源**。  
> **口径日期**：2026-07。  
> **旧项目代号**：`agent-langraph`（下文称「旧项目」）。  
> **新项目代号**：Agent Runtime 平台 / 智能写作与编码 Agent 平台（下文称「新平台」）。

> **给二次分析 AI 的提示**：请把本文视为封闭知识库（含 **§26 起机制级深潜** 与 **§43 代码核对结论**）。文中已嵌入旧对比、领域模型、数据流、能力设计、SLO、缺口、写作事故、工具/审批/超时默认值、Turn 时序、Harness 铁律与交付数据模型；不要假设还能读到源码或其它专文。数字/顺序冲突时以 §43 为准。若需批判或提炼亮点，请优先使用诚实边界章节，避免把「设计正确」夸成「已对齐 Cursor 全功能」。

---

## 目录

1. [一句话结论](#1-一句话结论)
2. [术语表](#2-术语表)
3. [产品定位与三重目标](#3-产品定位与三重目标)
4. [为何重写：旧项目问题全景](#4-为何重写旧项目问题全景)
5. [设计原则与明确非目标](#5-设计原则与明确非目标)
6. [新平台总体结构](#6-新平台总体结构)
7. [领域模型与状态机](#7-领域模型与状态机)
8. [Turn 执行内核：Intake + Agentic Loop](#8-turn-执行内核intake--agentic-loop)
9. [事件、SSE 与投影](#9-事件sse-与投影)
10. [双场景：写作与通用 Agent](#10-双场景写作与通用-agent)
11. [能力专题：RAG 与素材卡](#11-能力专题rag-与素材卡)
12. [能力专题：上下文编排](#12-能力专题上下文编排)
13. [能力专题：多 Agent 委派](#13-能力专题多-agent-委派)
14. [能力专题：Agent Harness](#14-能力专题agent-harness)
15. [改稿、审批、取消与超时](#15-改稿审批取消与超时)
16. [旧 → 新对照总表](#16-旧--新对照总表)
17. [迁移映射摘要](#17-迁移映射摘要)
18. [体验 SLO、自用体感与诚实缺口](#18-体验-slo自用体感与诚实缺口)
19. [写作交付事故与修复启示](#19-写作交付事故与修复启示)
20. [可证明性：Golden Turn](#20-可证明性golden-turn)
21. [技术栈与交付形态](#21-技术栈与交付形态)
22. [里程碑与实施状态](#22-里程碑与实施状态)
23. [对内叙事 / 简历叙事建议](#23-对内叙事--简历叙事建议)
24. [给外部 AI 的分析清单](#24-给外部-ai-的分析清单)
25. [FAQ](#25-faq)
26. [机制级深潜：一次 Turn 的完整时序](#26-机制级深潜一次-turn-的完整时序)
27. [机制级深潜：性能与复杂度硬约束](#27-机制级深潜性能与复杂度硬约束)
28. [机制级深潜：工具系统全景](#28-机制级深潜工具系统全景)
29. [机制级深潜：副作用分级与审批流](#29-机制级深潜副作用分级与审批流)
30. [机制级深潜：上下文引擎契约与多层防线](#30-机制级深潜上下文引擎契约与多层防线)
31. [机制级深潜：Cancel / Interrupt / Resume 权威语义](#31-机制级深潜cancel--interrupt--resume-权威语义)
32. [机制级深潜：三层超时与 Stall Watchdog](#32-机制级深潜三层超时与-stall-watchdog)
33. [机制级深潜：Agent Harness 六面、分期与铁律](#33-机制级深潜agent-harness-六面分期与铁律)
34. [机制级深潜：事件 envelope 与 SSE 拉取模型](#34-机制级深潜事件-envelope-与-sse-拉取模型)
35. [机制级深潜：Session 连续性与长会话](#35-机制级深潜session-连续性与长会话)
36. [机制级深潜：写作交付数据模型与 RAG 栈细节](#36-机制级深潜写作交付数据模型与-rag-栈细节)
37. [机制级深潜：Web 工作台契约](#37-机制级深潜web-工作台契约)
38. [机制级深潜：Golden 用例族与断言形态](#38-机制级深潜golden-用例族与断言形态)
39. [机制级深潜：配置、模型热生效与部署剖面](#39-机制级深潜配置模型热生效与部署剖面)
40. [机制级深潜：反模式清单与设计否决案](#40-机制级深潜反模式清单与设计否决案)
41. [机制级深潜：端到端用户旅程](#41-机制级深潜端到端用户旅程)
42. [机制级深潜：给分析 AI 的抽取模板](#42-机制级深潜给分析-ai-的抽取模板)
43. [与代码仓库核对结论与仍可补充项](#43-与代码仓库核对结论与仍可补充项)

---

## 1. 一句话结论

旧项目**领域概念大体正确**（Session / Run / Turn、写作交付、检索、上下文治理等），但**工程形态**把能力锁死在「单体进程 + 13 节点固定流水线」上，导致难维护、难取消、简单任务也慢、长会话易劣化。

新平台**不否定业务能力**，而是更换承载方式：

- **三服务拆分**：控制面 `api`、执行面 `runtime`、前端 `web`，加边缘 `gateway` 与 `postgres`；
- **单 agentic loop**：模型在循环内按需调工具，而不是人预先编排 13 个阶段；
- **场景扩展**：写作 / 通用 Agent 共用同一内核，差异只在 ScenarioProfile；
- **Agent Harness 加厚**：在 Intake / Context / Tools / Model / Guard / Proof 六面上补策略与可观测，**不靠再加 pipeline 节点**。

当前自用体感：**跟手、可打断、写作有资料锚定、长会话不至于很快崩**——已过「愿意打开做真实任务」的门槛；成熟度仍在加厚，**不是**宣称功能清单追平 Cursor / Claude Code。

---

## 2. 术语表

| 术语 | 含义 |
|------|------|
| **Agent Runtime** | 新平台的产品/架构定位：一个可长期运行的 agent 执行内核 + 多场景扩展 |
| **Scenario / ScenarioProfile** | 场景及其 YAML 配置：工具白名单、system prompt、子 agent 角色、审批策略、UI 布局 id |
| **writing** | 默认场景：长文写作、大纲、diff 改稿、资料引用 |
| **agent** | 通用场景：类 Cursor 的探索 / 改文件 / 跑命令 / 时间线 |
| **Turn** | 一次用户输入从受理到终态的业务闭环 |
| **Run** | 该 Turn 唯一的执行实例；与 Turn **1:1** |
| **Step** | Run 内一轮：assemble → model → tools → checkpoint；不暴露为独立 REST 资源 |
| **AgentEngine** | `while true` 推理循环；**不**按 scenario 名称写业务分支 |
| **TurnController** | Turn 启动准备与收尾：加载 Profile、Intake、写事件、更新终态 |
| **Intake** | 确定性输入编译与 shouldQuery 门控；**不是** LLM 意图分类图 |
| **ContextEngine** | 每步组装可见上下文，并做预算 / 压缩 / 折叠 / 裁剪 |
| **ContextEnvelope** | assemble 的权威输出结构：system 块、project/runtime 上下文、消息窗、工具表、预算报告等 |
| **Tool-mediated RAG** | 检索只通过工具进入下一轮上下文；禁止每轮预塞向量包 |
| **素材卡 / pin** | 写作场景把本轮写定资料钉进 system 前缀，并产生可观测事件 |
| **hot_files / context_refs** | 委派与会话用的短路径指针（通常 ≤12）；子 Agent 按需读文件，不整包拷贝父 messages |
| **`/verify`** | 用户触发的确定性引用扫描（无模型、不改草稿）；与 Turn 内 evidence/`unverified` 互补 |
| **remember / recall** | 按需长短时偏好记忆工具；独立仓；禁止每轮盲召 |
| **delegate** | 多 Agent 委派工具：子 Agent 独立跑完后**摘要回灌**主循环 |
| **Agent Harness** | 广义「包住模型、决定好不好用」的工程层；六面见 §14。早期曾称 Model Harness，现升格 |
| **Model 面** | Harness 子轨：生成策略、重试、快超时、prompt cache、usage 等 |
| **Golden Turn** | 固定输入 + 期望事件/终态/工作区断言的回归用例 |
| **Projection / TurnView** | 由事件异步折叠出的 UI 视图；前端不猜 Turn「阶段」 |
| **SSE** | 服务端推送流；api 独占对外 SSE，runtime 只写事件表 |
| **workflow vs agent** | workflow = 人预先编排阶段；agent = 模型在带工具的循环里决定下一步 |

---

## 3. 产品定位与三重目标

### 3.1 定位

**一个内核，多个 Scenario。**

- 默认产品入口：`writing` 写作模式  
- 第二入口：`agent` 通用 Agent 模式  
- 扩展宪法：一个 Runtime，多个 Scenario；一个 Loop，多组 Tool；一条事件管道，多种工作台布局  

交互标准对齐成熟编码 agent：**流式、可打断、过程可见、变更可审（diff）**。

### 3.2 三重目标必须同时成立

| 目标 | 含义 | 验收取向 |
|------|------|----------|
| **可长期运行** | 架构可维护、可扩展，数周数月持续用 | 边界清晰、配置单一、状态可恢复 |
| **自用好用** | 跟手、可停、diff、长会话不劣化 | 体验 SLO + 日常任务 |
| **对外成熟** | 行为可回归、可 demo、可讲清技术点 | Golden Turn + 可观测 + 诚实缺口 |

成熟 agent 三角可记为：

```text
        好用（SLO、diff、长会话）
              ╱╲
  可长期运行 ╱  ╲ 对外成熟
            ╲  ╱
             ╲╱
    同一套 turn_events 事实链
    + Context / RAG / delegate 必须走主路径且有 golden
```

---

## 4. 为何重写：旧项目问题全景

### 4.1 旧项目保留了什么

旧项目已经验证了大量**正确的领域概念**，新平台刻意保留而非推倒：

- Session / Run / Turn 语义；
- 写作交付链路、证据/引用意识；
- 上下文治理、检索、子任务协作等「能力清单」。

重写的对象是**承载方式**，不是「这些能力不该存在」。

### 4.2 工程形态问题

| 问题 | 表现 | 后果 |
|------|------|------|
| 单体进程 | 一个 FastAPI 进程挂载 API、执行图、Web 静态、调度器、多种 lifespan | 启动慢、故障域大、无法对执行面独立扩缩 |
| 模块平铺 | `services/` 一类目录 200+ 模块 | 边界模糊、循环依赖、改一处影响面难估 |
| 配置过载 | 800+ 行配置 YAML + 多份 compose overlay | 本地/生产行为不一致，排障靠 Makefile 记忆 |
| 文档脱节 | 超长架构文描述理想态，代码已多处分叉 | 架构讨论无法落到可执行边界 |

### 4.3 编排内核问题：13 节点固定 pipeline

旧执行脊柱大致为：

```text
event_classification → acknowledge → interrupt_control → incremental_planning
→ retrieval / tool / engineering → context_governance → reasoning_or_writing
→ verification → policy → output → END
```

约 **13 个节点、多个 router**。这是典型 **workflow**：路径由人预先编排。

具体伤害：

1. **简单输入也跑完整链路**（分类→规划→检索→验证），延迟与成本浪费。  
2. **每加场景就改图、加节点、加 router**，改一处牵动全图。  
3. **检索/验证是强制阶段**，模型无法跳过或按需多次调用。  
4. **业务与编排耦合在图里**，难测、难演进。  
5. **Cancel 难贯串**：图节点长事务；取消传不到 stream / 子进程 → 用户体感「点了停不住」。  
6. **无界等待**：缺统一的 model/tool/step 超时与卡住检测 → 流程可卡数百秒。  
7. **状态膨胀**：大 `AgentState` + 节点间 dict 缺 schema → 「某步 str 对不上对象」类故障。

### 4.4 用户体感层面的旧痛

| 体感 | 对应根因 |
|------|----------|
| 简单改一句也慢 | 强制全链路 |
| 卡很久不知在干什么 | 节点黑盒 + 弱可观测 |
| 很难即时取消 | cancel 未贯串 |
| 长会话越用越糊/越贵 | 上下文治理弱或与节点耦合 |
| 「能跑」但不敢改 | 边界不清、回归靠人点 |

---

## 5. 设计原则与明确非目标

### 5.1 设计原则（摘要）

| # | 原则 | 含义 |
|---|------|------|
| P1 | Docker First | 容器为验收路径；`compose up` + smoke 可证明「能启动」 |
| P2 | 边界先于功能 | 契约先于代码；**禁止跨服务 Python import** |
| P3 | 十二要素配置 | 环境变量 + Settings；配置入口唯一 |
| P4 | 渐进交付 | stub → 双场景闭环 → 能力融合 → 运维增强 |
| P5 | 可测试 | healthcheck + compose + 单测 + golden |
| P6 | 场景扩展 | 新能力 = Profile + 工具注册，**不改 loop** |
| P7 | 体验可测 | TTFB、Cancel、重连等有 SLO |
| P8 | 行为可回归 | Golden Turn + CI |
| P9 | Intake 确定性 | 门控与编译非意图 Pipeline |
| P10 | 能力走主路径 | Context / RAG / delegate 必须被 loop 调用且有 golden；禁止摆设模块 |
| P11 | 边界可校验 | 命令/事件/tool 用 schema，防字段漂移 |
| P12 | 执行有上界 | model/tool/step 超时 + Stall Watchdog |
| P13 | 运营配置热生效 | 模型供应商经 Web→DB；Turn 边界生效，无需重启服务 |
| P14 | Agent Harness 厚度 | 成熟度差在六面策略，不靠加 pipeline 节点 |

### 5.2 当前非目标

以下**刻意不做**或延后，避免范围爆炸：

- Kubernetes / Helm、多区域 HA；
- 完整移植旧 API 表面；
- MCP / A2A / 模型 Marketplace 全量；
- 为「功能清单追平 IDE」而重写 while 语义或恢复固定大图。

---

## 6. 新平台总体结构

### 6.1 部署拓扑

```text
Client → gateway → web          （静态工作台）
                 → api → runtime → postgres
                              ↘ /data, /workspace
```

| 组件 | 职责 | 明确不做 |
|------|------|----------|
| **gateway** | TLS、反向代理路由 | 业务状态 |
| **api** | 鉴权、资源/命令、**独占 SSE**、投影刷新 | 不跑 agentic loop |
| **runtime** | Turn 执行、工具、模型、checkpoint、检索索引 | 不公网暴露；不做 UI 投影 |
| **web** | 按 `scenario_id` 换布局的工作台 | 不猜 Turn 阶段；不直连 runtime |
| **postgres** | 会话、Turn、事件、checkpoint 元数据、供应商配置等 | — |

「三服务」口语专指 `api / runtime / web`；部署上通常还有 gateway + postgres，共五个容器级组件。

### 6.2 拆分带来的好处

| 好处 | 说明 |
|------|------|
| 故障域隔离 | runtime OOM / 模型卡死不直接拖死鉴权与静态页 |
| 镜像变小 | api 镜像不必打进 embedding / 重依赖 |
| 安全面收敛 | runtime 仅内网；公网只到 gateway/api |
| 扩展路径清晰 | 未来可多 runtime 副本；控制面保持轻量 |
| 团队边界清晰 | API/契约 vs 执行内核 vs 前端体验 |

代价：api↔runtime 多一次内网 hop；需维护内部 token 与契约。相对旧单体，这是**可接受的复杂度交换**。

### 6.3 逻辑分层

| 层 | 承载 | 职责 |
|----|------|------|
| 边缘 | gateway | 入口 |
| 控制面 | api | CRUD、命令、鉴权 |
| 实时 | api realtime | SSE 读 `turn_events` |
| 执行面 | runtime | loop + tools + model |
| 异步投影 | api projection / worker | 刷新 views，不阻塞主路径 |

### 6.4 仓库心智模型（无代码也能理解）

```text
平台/
├── 部署：单一 docker-compose 入口 + 可选 profile（queue、retrieval）
├── api 服务：HTTP + SSE + 投影
├── runtime 服务：TurnController + AgentEngine + Context + Tools + Model
├── web 服务：写作布局 / Agent 布局共享 realtime 层
├── contracts：OpenAPI、事件 schema、DDL、共享校验包
└── eval/golden：行为契约用例
```

**禁止**跨服务直接 import Python 包；接缝只走 HTTP/DB/契约。

---

## 7. 领域模型与状态机

### 7.1 对象关系

```text
Session (1)
  └── Turn (N)          一次用户输入的受理闭环
        └── Run (1)     与 Turn 严格 1:1 的执行实例
              └── Step (M)  循环内一步（事件粒度，无独立资源 API）
```

| 约束 | 说明 |
|------|------|
| Turn↔Run 1:1 | 禁止一个 Turn 多个并发 Run；重试/恢复仍用同一 `run_id` |
| 新消息新 Turn | 禁止跨 Turn 共享未结束 Run |
| Step 不暴露 REST | 只出现在事件与日志的 `step_index` |

### 7.2 Turn 状态

```text
pending → running → completed
              ├→ waiting_approval → running → …
              ├→ failed
              └→ cancelled
```

### 7.3 为何比旧状态更好用

- **事实在事件**：UI 与调试都以 `turn_events` 为准；  
- **终态可解释**：`max_steps` / `budget_exceeded` 等可标为可解释终止，不一定是 `failed`；  
- **审批可挂起**：`waiting_approval` + checkpoint，而不是卡死在图节点里。

---

## 8. Turn 执行内核：Intake + Agentic Loop

### 8.1 两层结构

```text
TurnController
  · 加载 ScenarioProfile → ToolScope
  · InputCompiler + shouldQuery
  · 立即写 turn.accepted（保 TTFB）
  · 终态与异步收尾触发

AgentEngine  while true:
  1. ContextEngine.assemble
  2. ModelGateway.stream
  3. 解析 text / thinking / tool_use
  4. 无 tool_use → final 结束
  5. 有 tool_use → ToolExecutor
  6. tool_result 回灌 messages → checkpoint → 下一轮
```

一句话：`TurnController` 管「这一轮怎么开怎么收」；`AgentEngine` 管「想一步、调工具、再想」；**引擎不感知 scenario 名字**。

### 8.2 Intake：确定性，不是意图分类

旧 `event_classification_node` **删除不恢复**。

```text
用户输入
  → InputCompiler（确定性：斜杠命令、@path、附件、选区）
  → shouldQuery 门控（确定性）
  → [否] 本地响应，零模型调用，Turn 结束
  → [是] 进入 AgentEngine；首轮由模型决定直答还是 tool_use
```

| 问题 | 谁负责 |
|------|--------|
| 写作还是 Agent？ | 用户选择 / API 的 `scenario_id`，**不由 LLM 猜** |
| 要不要调模型？ | shouldQuery 规则表 |
| 改哪、要不要工具？ | 首轮模型 |
| 复杂多步？ | `update_plan` / `delegate` 等工具按需 |

`/help`、`/version` 等可短路：**零模型调用**，既省钱也跟手。

### 8.3 核心状态：messages 即状态

相对旧大 `AgentState`：

> agent 的记忆、轨迹、工具结果，主要编码在有序 `messages` 序列里。

TurnState 概念字段：`turn_id`、`session_id`、`run_id`、`scenario_id`、`messages`、`step_count`、`max_steps`、`usage`、`cancelled` 等。

好处：回放、计费、debug、压缩都有统一载体；边界用 schema 校验，减少「节点间 dict 对不上」。

### 8.4 终止条件

显式终止，例如：`final` | `max_steps` | `cancelled` | `budget_exceeded` | `fatal_error`。  
失控风险从「图里隐式」转移到「护栏显式」——这是 agent 形态的必要交换，必须用预算与 Cancel 补齐。

### 8.5 LangGraph 在新平台中的真实角色

依赖里可能仍有 LangGraph，但决策是：

- **只做机制层**：loop / checkpoint / interrupt；  
- **图退化为单循环** `agent ⇄ tools`；  
- **不承载业务编排**；业务不绑定框架，未来可换成裸 `while`。

对外叙事时：**不要**把新平台说成「LangGraph 多节点工作流平台」——那正是旧债。

---

## 9. 事件、SSE 与投影

### 9.1 权威数据流

```text
用户 POST StartTurn
  → api 创建 Turn/Run
  → runtime 执行并 append-only 写入 turn_events
  → PostgreSQL NOTIFY + api LISTEN（另有短轮询兜底）
  → api SSE → web
  → api projection 异步 UPSERT turn_views
```

关键纪律：

- runtime **不**直接对浏览器开 SSE；  
- **不以内存 channel 作为跨服务唯一事件源**；跨服务事实在 Postgres；  
- 投影**不阻塞** Turn 主路径；  
- web **不猜阶段**：进行中靠 SSE，重连/终态靠 `TurnView`。

### 9.2 四层协议心智

| 层 | 作用 |
|----|------|
| Resource | 会话、Turn、文件等资源 |
| Command | StartTurn、CancelTurn、ApproveToolCall 等 |
| Event | 事实流：`turn.accepted`、`turn.token`、`tool.*`、`patch.proposed`… |
| Projection | 给 UI 的折叠视图 |

旧前端常「自己拼阶段」；新平台用事件+投影，**状态同源、可重建**。

### 9.3 对体感的直接意义

- 发送后很快看到「已受理」；  
- token / 工具增量流式出现；  
- 断线可用 Last-Event-ID 类机制续流；  
- Stop 后 UI 可乐观停渲染，再与 `turn.cancelled` 对齐。

---

## 10. 双场景：写作与通用 Agent

### 10.1 宪法：什么冻、什么扩

| 层级 | 内容 | 策略 |
|------|------|------|
| 内核冻结 | loop、ContextEngine、ToolExecutor、事件管道、领域对象 | Phase 1 后尽量少改 |
| 场景扩展 | Profile：工具表、prompt、子角色、审批、布局 | **新能力优先加这里** |
| 工具扩展 | 工具实现注册；Profile 只登记名字 | 加能力 = 注册工具 |
| 展示扩展 | 新事件 + Projection + 前端场景组件 | 不在 runtime 拼 UI |

**禁止**：

1. 在引擎里 `if scenario == "writing"` 写业务；  
2. 为每个场景复制一套 loop / 事件管线；  
3. 用新固定 pipeline 节点承载场景能力；  
4. runtime 直接拼装 UI 结构。

### 10.2 写作场景用户要什么 → 怎么映射

| 需求 | 用户要什么 | 映射 |
|------|------------|------|
| 结构 | 大纲、章节 | `outline.md`、`sections/`、`update_outline` |
| 成稿 | 按节流式 | `draft_section`、流式 delta 事件 |
| 改稿 | 看见 diff、可收可拒 | 模型 `propose_patch` → UI 审阅 → 用户 Accept 后 `accept_patch` 命令落盘 |
| 证据 | 资料与引用 | `search_sources`、`check_citation`、素材卡 pin |
| 质量 | 事实/风格 | `delegate`：researcher / fact_checker / stylist 等 |
| 交付 | 导出 | `export_document`、artifacts |
| 交互 | 跟手可停 | 共享 SSE / Cancel；UI 偏文稿编辑器 |

默认**关闭** `run_command`、代码库级 `grep`，避免写作被工程工具干扰。

### 10.3 Agent 场景用户要什么 → 怎么映射

| 需求 | 映射 |
|------|------|
| 探索 | `read_file`、`glob`、`grep` |
| 检索 | `search_codebase` / `search_sources` |
| 执行 | `run_command`、`run_tests`；强审批 |
| 改动 | `propose_patch` 或受控写文件 |
| 规划 | `update_plan`；可选 `delegate(planner)` |
| 协作 | `delegate`：explore / verify / edit |
| 交互 | Timeline + Artifact |

### 10.4 共享约 70% 原语

同一套：loop、patch、读写、delegate、流式取消、ContextEngine、事件管道、Turn/Run 1:1。  
这是相对「两套系统」的核心结构优势：**改一次内核，两个产品入口受益**。

第三场景（如访谈 `interview`）= 新 Profile + 工具登记 + UI，不改内核。

---

## 11. 能力专题：RAG 与素材卡

### 11.1 设计选择：Tool-mediated RAG

| 做法 | 是否采用 | 原因 |
|------|----------|------|
| 每轮预注入向量检索包 | **禁止** | 噪声大、贵、慢；简单问题也被检索绑架 |
| 独立 retrieval 服务存在但不被 loop 调用 | **禁止** | 摆设模块，无法被 golden 证明 |
| 检索作为工具，结果进 `tool_result` 再 assemble | **采用** | 按需、可多次、可跳过、可观测 |

写作侧主工具：`search_sources`。  
Agent 侧：`search_codebase`（可先有退化实现，再增强语义检索）。

### 11.2 对写作产品的增强

通过按需 RAG，增强了：

- **资料锚定**：成稿应能指向 sources，而不是空口生成；  
- **引用可核对**：配合 `check_citation` 与侧栏证据视图；  
- **信噪比**：只有模型认为需要时才检索，避免「每轮都塞一包向量」。

另有 Turn 级检索次数预算等护栏，防止检索死循环烧钱。

### 11.3 素材卡写定

写作场景支持把本轮相关资料 **pin** 进 system 前缀，并产生可观测事件。

意图：

- 「本轮写定」对用户可见，不只存在于模型隐式记忆；  
- 稳定前缀有利于后续 prompt cache；  
- 改稿时仍有明确资料锚，减少漂移。

### 11.4 检索实现演进的诚实说明

- 默认 hybrid（BM25 + 向量 + RRF）；lexical rerank 默认可开；cross-encoder 默认关；  
- **热路径只 load + search**：禁止在 `search_sources` 同步全量建索引；索引走异步 worker；空/滞后索引可 keyword 兜底并提示 `index_lag`；  
- 可选 pgvector（HNSW）后端；默认可文件向量库；hash embedding 降级保证无重模型也能跑通契约；  
- 两级召回（文档摘要通道 ∥ chunk 通道）默认可开，超时降级 chunk-only；  
- retrieval 可作为 compose profile 增强，不是强制所有环境装齐 GPU；  
- 「向量索引可用」≠「每轮强制 RAG」。

---

## 12. 能力专题：上下文编排

### 12.1 问题

长会话若无限累积 messages：

- 延迟上升、费用上升；  
- 模型注意力被旧噪声稀释；  
- 最终「越聊越糊」。

硬靠「更大窗口」不可持续。

### 12.2 做法

每 Step 调用 `ContextEngine.assemble`，输出 `ContextEnvelope`，再送给模型。

压缩/治理链按**代码实际顺序**执行（与实现一致）：

1. **budget**：工具结果字符预算截断；  
2. **microcompact**：局部折叠高噪音工具结果；  
3. **collapse**：填充率 ≥ **0.80** 时折叠工具历史；  
4. **snip**：填充率 ≥ **0.90** 时丢弃最旧消息组；  
5. **autocompact**：填充率 ≥ **0.95** 时整体摘要兜底；  
另有 session transcript 滚动；`/compact` 可强制压缩。  

> 注意：早期设计文曾写 snip 在 microcompact 之前；**以 runtime `ContextEngine` 实现顺序为准**。

原则：

- **禁止**未达阈值就无脑整窗摘要；  
- 落库 trim 应确定性优先；  
- 热路径成本要可度量。

### 12.3 好处

- 长会话可持续自用；  
- 质量与成本不线性爆炸；  
- 与「能力走主路径」一致：assemble 不是装饰，而是每步必经。

---

## 13. 能力专题：多 Agent 委派

### 13.1 旧形态

旧项目常见 supervisor 分解 / worker / merge 图节点：子任务协作绑在 workflow 上。

### 13.2 新形态

仅通过 **`delegate` 工具**：

1. 主 Agent 决定委派；  
2. 传入 **task + 短备注 + 路径指针**（`context_refs` / `paths`），并可由运行时注入父会话 **`hot_files`（≤12 条路径）**——只传指针，不贴巨量正文；  
3. 子 Agent 以独立 `AgentEngine` 运行（工具面按类型收窄，深度 ≤2）；  
4. **摘要回灌**主 `messages`；  
5. **禁止**把子会话全量历史倒灌进主窗口。

写作侧角色示例：researcher、fact_checker、stylist…  
Agent 侧：explore、verify、edit、planner…  
事实核查默认不挂交付末尾；用户可 `/verify`（确定性扫引用），或离线低比例抽样。

### 13.3 好处与风险

| 好处 | 风险与护栏 |
|------|------------|
| 复杂任务可拆 | 子 Agent 失控 → 超时、步数、审批、深度上限 |
| 主上下文不被撑爆 | 强制摘要回灌 + 路径指针优于整包 messages |
| 不改主 loop | 角色在 Profile 配置 |

---

## 14. 能力专题：Agent Harness

### 14.1 命名演进

- 早期：「**Model Harness**」——只管模型调用外围；  
- 现在：「**Agent Harness**」——广义六面成熟度总纲；  
- Model 仍是子轨之一。

对分析者：若只说 Model Harness，口径已过时；若把「整个平台」都叫 Harness 也可以，但应能拆开六面。

### 14.2 六面是什么

| 面 | 管什么 |
|----|--------|
| **Intake** | 输入编译、shouldQuery、`@path` 预读 |
| **Context** | Envelope、compact、assemble 复用、热文件指针 |
| **Tools** | 工具范围、审批、超时、只读并行、description 质量 |
| **Model** | 供应商配置、生成策略、重试/错误分类、快超时、prompt cache、usage |
| **Guard** | Cancel 贯串、model/tool/step 超时、stall watchdog |
| **Proof** | Golden、延迟门禁、retry/cache/assemble 等可观测字段 |

**不是**：换一个更强模型；加 workflow 节点；在引擎里按 scenario 塞策略。

### 14.3 两条主线

| 主线 | 目标 | 风险 | 兜底 |
|------|------|------|------|
| 能力 | 少猜、少失败、少劣化 | 上下文变厚 → 更慢更贵 | 延迟预算 |
| 性能 | 跟手、可打断 | 为省时牺牲正确性 | golden + SLO |

铁律摘要：

1. **受理优先**：`turn.accepted` 先于重活；  
2. **快失败**：首次尝试短超时，而不是干等到满超时；  
3. **可打断压倒可靠**：Cancel 必须能打断 backoff / assemble / 预读；  
4. **加厚先能抵消**：显著增大输入应有 cache 或硬上限；  
5. **可测才算数**；  
6. **策略不进引擎分叉**。

### 14.4 分期直觉

典型顺序：先稳调用 → 再 cache 降本加速 → 再加厚上下文/预读/只读并行 → 再成本精修。  
「先 cache 再加厚上下文」是为了避免性能倒退窗口。

到 2026-07 口径：AH1 及 AH2–AH4 核心路径已大量落地；仍可能有细调与 golden 加固。分析时请同时看 §18 缺口，避免「文档写了就等于体验完美」。

---

## 15. 改稿、审批、取消与超时

### 15.1 Diff 改稿

主路径：模型调用 `propose_patch` → 事件 `patch.proposed` → 用户在 UI Accept/Reject → **api/runtime 命令**执行落盘（`accept_patch` → 内部 `apply_patch`）。

要点：

- 写作 Profile **不把** `apply_patch` 暴露给模型工具表；落盘走用户审阅后的控制面命令。  
- `apply_patch` 工具仍注册在 runtime，可供需要审批的路径使用，但写作主体验是「审阅后命令落盘」。  

**禁止**静默覆盖用户未审文稿。这是写作与 Agent 共享的「变更可审」体验基线。

### 15.2 工具审批

工具带副作用分级与审批策略。例如 Agent 场景 `run_command` 需工具级审批；写作改稿主要靠 **Turn 结束后的 patch 审阅 UI**，`propose_patch` 在默认 Profile 下**不**走 `waiting_approval` 工具门控。  
审批中 Turn 进入 `waiting_approval`，与 Stop/Cancel 产品语义要分开：批准/拒绝 ≠ 简单 Stop。

### 15.3 Cancel

目标体感：点 Stop，**立刻停本地渲染**，并尽快让服务端进入 `cancelled`。

需要 Cancel 能打断：

- 模型流；  
- 重试 backoff sleep；  
- assemble / 预读 I/O；  
- 长工具执行。

### 15.4 超时与 Watchdog

三层超时概念：model / tool / step，再加 stall watchdog，防止无界 hang。  
相对旧项目「卡几百秒」，这是结构级修复，不只是调参。

---

## 16. 旧 → 新对照总表

| 维度 | 旧项目 | 新平台 |
|------|--------|--------|
| 进程形态 | 单进程全能 | api / runtime / web 拆分 |
| 编排 | 13 节点 workflow | 单 agentic loop + 工具 |
| 检索/验证 | 强制阶段 | 可选工具 |
| 场景扩展 | 改图加 router | Profile + 工具登记 |
| 状态 | 膨胀 AgentState | messages 为主 |
| 取消 | 难贯串 | abort + SLO + 乐观 UI |
| 前端状态 | 易自行拼阶段 | SSE + Projection |
| 配置/部署 | 多 overlay 复杂组合 | Docker First，单一入口 |
| 成熟度补洞 | 倾向加节点 | Agent Harness 六面加厚 |
| 可证明 | 弱 | Golden + 延迟门禁 |
| LangGraph | 业务编排主载体 | 机制壳，可替换 |

对照成熟产品（Cursor / Claude Code 类）：新平台**取向一致**——单 loop、工具中心、流式、上下文压缩；差距在 Harness 厚度与产品打磨，不在「要不要回到大图」。

---

## 17. 迁移映射摘要

说明「旧能力去哪了」，便于分析「是否真的重写而非换皮」。

| 旧模块/节点 | 新归属 |
|-------------|--------|
| task API | api 服务 |
| graph + nodes | runtime 单循环引擎 |
| writing_* 服务 | writing Profile + 核心工具 |
| web | web 服务按场景布局 |
| supervisor 分解合并 | `delegate` + 子角色 |
| retrieval_* | `search_sources` / `search_codebase` |
| prompt_context_gateway | ContextEngine |
| tool_* | 工具注册表 + Profile 白名单 |
| event_classification | **删除** → Intake |
| acknowledge | `turn.accepted` 快首包 |
| retrieval_node | search_* 工具 |
| context_governance_node | 每步 ContextEngine |
| verification_node | `check_citation` / `run_tests` 等工具 |
| policy / human_review | 工具级审批 |
| supervisor_* | `delegate` |

---

## 18. 体验 SLO、自用体感与诚实缺口

### 18.1 体验 SLO

| 指标 | 目标取向 |
|------|----------|
| TTFB | `turn.accepted` 类受理反馈尽快出现 |
| 首模型 token | 允许长于 TTFB，但仍有上限目标 |
| 流式 Cancel | 尽快到 `turn.cancelled` |
| UI Stop | 本地立即停渲染 |
| SSE 重连 | 短时断线可续、尽量无缺口 |
| 长会话 | 多 Turn 后延迟不明显线性恶化 |
| 终态一致 | TurnView 与事件终态可对账 |

TTFB 与首 token **不要混为一谈**。

### 18.2 写作 / Agent 自用门槛

写作最低标准示例：大纲可见、按节流式、改稿必 diff、证据可核对、默认无危险 exec。  
Agent 最低标准示例：工具时间线可见、变更可审、exec 可控可取消、计划可选展示。

### 18.3 当前体感结论

基于日常自用与阶段验收：

**已经明显好于旧项目**

1. 发消息有即时受理与流式输出；  
2. Stop 不再是「心理安慰剂」；  
3. 写作资料检索与素材卡进入主路径，成稿更有锚；  
4. 双场景共用内核，切换不必换系统；  
5. Docker + golden 让「能跑且行为大致稳定」可重复验证；  
6. 长会话有压缩链托底，不至于旧项目那样快速不可用。

**已相对早期缺口加厚（2026-07 中下旬）**

1. 工具参数 JSON Schema 预校验（失败不进 handler）；  
2. 引用 evidence / `unverified` 标记 + 用户 `/verify` 与离线抽样核查；  
3. 按需记忆工具 `remember` / `recall`（不每轮盲召）；  
4. Guard：模型出站 allowlist、出站/日志 PII 正则脱敏、写出前 secret 扫描；  
5. 晚步 / 交付后阶段收缩工具表；打字 debounce 预热嵌入器与索引加载；检索热路径不建索引。

**必须诚实保留的缺口**

1. 与顶级 IDE 内嵌 agent 仍有产品与 Harness 细调差距；  
2. live 模型质量/延迟依赖供应商；stub/recorded golden 绿 ≠ 线上永远聪明；  
3. 非目标范围内的 K8s/MCP 市场等未做；  
4. 写作交付曾出现「Turn completed 但导出物离谱」类事故——说明**完成态 ≠ 交付正确**，需要产物诚实性与路径一致性纪律；  
5. 诊断 UI 若用关键词误判「该检索却未检索」，会造成「RAG 坏了」的错觉——观测层与执行层可能错位；  
6. 企业万档 ACL / Elastic 级倒排、多租户、真实多表召回（`search_records` 仍为 stub）未完。

**一句话体感**：架构形状对了，自用已过门槛；护栏与检索前置已加厚；下一阶段是规模与交付诚实性，而不是再造一张大图。

---

## 19. 写作交付事故与修复启示

2026-07 写作模式曾暴露一组高价值教训，分析新平台时**不应省略**：

### 19.1 典型现象

- 用户要求「针对资料写两章并形成一个文件」；  
- Turn 显示 completed，对话总结看起来正常；  
- 但导出文件可能是提纲 + 占位 + **无关大文档拼接**；  
- 真正成稿可能落在 revisions 类目录，用户打开的 export 路径却不对；  
- `sections/` 与 eval fixture / 历史残留共用目录时，导出可能吞进测试垃圾。

### 19.2 根因类型

| 类型 | 说明 |
|------|------|
| 路径不一致 | draft 写一处、export 读另一处 |
| 通配过宽 | export 拼接整个目录而非本轮目标 |
| 完成态过早 | 事件 completed 不保证产物可读 |
| 工作区污染 | 用户稿与测试残留未隔离 |
| 观测误报 | 「提到资料」就被诊断为必须 search_sources |

### 19.3 对架构评价的含义

新平台的 loop/Harness 再正确，**交付工具链仍可能毁掉体感**。  
因此「结构优势」要同时包含：

- 运行时内核正确；  
- **产物路径、导出语义、用户可见失败信号**正确。

这是相对纯架构文档的重要补充：体感来自端到端，不只来自 loop 形状。

---

## 20. 可证明性：Golden Turn

### 20.1 原则

- Golden 是行为契约，不是演示脚本；  
- Eval 不阻塞主路径；  
- 观测与事件同源。

### 20.2 能力融合阻断项

进入更高阶段前，至少要用 golden 证明：

| 能力 | 证明什么 |
|------|----------|
| ContextEngine | 大输入触发压缩策略 |
| RAG 写作 | 真正调用 search_sources 且进入成稿路径 |
| RAG agent | search_codebase 被调用且可见 |
| 多 Agent | delegate 有子 agent 起止事件且主 Turn 完成 |

这直接针对旧世界「模块写了但从不上主路径」的失败模式。

### 20.3 模型模式

用例可在 stub / recorded / live 下跑：  
stub/recorded 保回归确定性；live 验真实供应商，但不应用 live 不稳定掩盖契约失败。

---

## 21. 技术栈与交付形态

### 21.1 实际核心技术

| 层 | 技术 |
|----|------|
| 后端 | Python、FastAPI |
| 存储 | PostgreSQL |
| 前端 | React、TypeScript；Vite 构建；静态 nginx 部署 |
| 实时 | SSE |
| 交付 | Docker / Docker Compose |
| 校验/契约 | OpenAPI、JSON Schema、共享 contracts 包 |
| 可选增强 | 本地 embedding、队列 worker、OpenTelemetry 等 |

LangGraph：**机制依赖，非业务卖点**；对外技术栈叙述可不强调，以免误解为旧式图编排平台。

### 21.2 交付验收直觉

全新机器期望路径：配置环境变量 → compose 启动 → health 全绿 → 打开 Web → 创建会话 → smoke/golden 可跑。  
配置入口应单一，避免「只有某台机器 Makefile 记得怎么起」。

---

## 22. 里程碑与实施状态

| 阶段 | 含义 |
|------|------|
| Phase 0 | 容器骨架、最小 SSE、stub golden |
| Phase 1 | 管道：patch/diff、timeline、SLO |
| Phase 1b | 能力融合：Context / RAG / delegate 有 golden |
| Phase 2+ | 检索运维、多角色、live eval、metrics 等 |
| Phase 3+ | 日常自用数周不弃用 |
| Phase 4 | CI profiles、nightly live 等 |

到 2026-07 文档口径：Phase 0–4 核心能力大体对齐；Agent Harness 核心路径推进中/部分完成。  
**分析时请把「阶段完成」理解为可演示可回归，而不是零缺陷。**

---

## 23. 对内叙事 / 简历叙事建议

### 23.1 推荐四条能力叙事

1. **通过按需 RAG 与本轮素材卡写定，增强了写作成稿的资料锚定、引用可核对与改稿信噪比。**  
2. **通过 Agent Harness 的 Model 面统一重试、快超时与生成策略，增强了抖动下首 token 稳定与 Turn 可中断。**  
3. **通过上下文编排的预算压缩与折叠裁剪，增强了长会话可持续性，抑制窗口膨胀带来的质量漂移。**  
4. **通过多 Agent 委派与摘要回灌，增强了调研核验等复杂写作子任务的拆解效率，且不撑爆主上下文。**

### 23.2 叙事纪律

- 先讲**用户结果**，再讲结构；  
- 保留 RAG、Harness 等面试官能懂的词；  
- Context / Multi-Agent 用中文说清机制；  
- 不要吹成「已完全对齐 Cursor」；  
- 可主动提：完成态与交付诚实性、观测与执行对齐，是你们踩过坑后的加成认知。

### 23.3 项目名称与技术栈精简示例

- 名称：智能写作与编码 Agent 平台  
- 技术栈：Python · FastAPI · PostgreSQL · React · TypeScript · SSE · Docker  

---

## 24. 给外部 AI 的分析清单

若你是接收本文的分析模型，建议按下列问题输出，避免空泛夸奖：

1. **架构是否自洽？** loop 冻结 + Profile 扩展 + Harness 六面是否互相打架？  
2. **相对旧项目的不可逆改进有哪些？** 哪些只是换皮？  
3. **最大风险是什么？** 模型路径不确定、交付诚实性、观测误报、Harness 性能回退等。  
4. **若只留三个对外亮点，应留哪三个？** 并给出不夸张的表述。  
5. **下一步 30 天最该做的三件事？** 必须服从「厚且快」与 golden。  
6. **简历版四条是否过火？** 标出任何无法被本文支撑的措辞。  
7. **把本文压缩成一页纸**给没空读长文的人。

---

## 25. FAQ

**Q：新平台是不是把旧项目推倒重来？**  
A：概念层多有继承；工程与编排层是重写。目标是换承载，不丢已验证能力。

**Q：为什么不用固定 pipeline「更可控」？**  
A：开放式写作/编码任务用 agent 更合适；可控性改由 Intake、审批、预算、Cancel、golden 提供，而不是用强制阶段假装可控。

**Q：两个产品是不是两套系统？**  
A：不是。同一 Runtime，两个 ScenarioProfile + 两套 UI 布局。

**Q：有 LangGraph 是不是又走回旧路？**  
A：否。仅机制层；业务在 loop/工具/Profile。对外勿按「LangGraph 工作流平台」宣传。

**Q：RAG 是不是核心卖点？**  
A：是写作证据链的关键卖点，但是 **Tool-mediated RAG**，不是「每轮向量预注入平台」。

**Q：体感还可以，能否对外说成熟？**  
A：可说「设计正确、可自用的早期平台」；成熟应绑定 golden/SLO/诚实缺口，而不是形容词升级。

**Q：最大结构优势一句话？**  
A：**把「加能力」从「改大图」变成「加工具/加厚 Harness」，并让能力必须走上主路径且可回归。**

---

## 文末：独立文档仓库使用说明

将本文拷贝到独立仓库时建议：

1. 保留本文件名或改为 `agent-platform-highlights.md`，但**不要删减 §18–§19**；  
2. 若需拆分，优先拆「对照表」「Harness」「写作事故」为附录，**主文仍保留结论与缺口**；  
3. 版本头更新日期与「基于 2026-07 口径」；  
4. 给 AI 分析时，把 §24 一并粘贴为任务指令。

本文旨在让**不读代码的人与模型**也能完整理解：新平台相对旧项目好在哪里、结构为何更好、体感为何「还可以」、以及还有哪些不能吹过头的边界。

**请继续阅读第二部（§26 起）**：机制级时序、工具/审批/上下文/Cancel/超时/Harness/交付/RAG/Web/Golden/反模式与抽取模板。无第二部则分析粒度不足。


---

# 第二部：机制级深潜（极细）

> 以下章节把「为什么好」落成「系统究竟怎么跑」。独立文档仓库与分析 AI 应把第二部与第一部同等对待。数值为平台设计默认值；Profile / env 可覆盖。口径 2026-07。

---

## 26. 机制级深潜：一次 Turn 的完整时序

### 26.1 控制面受理

1. 用户在 Web 发送消息；请求经 gateway 到 api。  
2. api 校验命令 schema、鉴权、幂等键 `client_request_id`。  
3. api 创建 `Turn` + `Run`（1:1），状态大致 `pending` / `accepted`。  
4. api 向 runtime 发内部命令：`POST /internal/commands/start-turn`（带内部服务 token）。  
5. Web 同时订阅 `GET /turns/{id}/stream` SSE，用 `since_sequence` / Last-Event-ID 支持重连。

### 26.2 TurnController 启动序列

```text
1. 加载 ModelGateway 配置
   - 优先 DB 中激活的 model_provider_profiles
   - 否则 env fallback
   - 整轮 Turn 固定该 provider/model，中途不热切（避免半轮行为漂移）
2. 加载 session 上下文
   - 优先 session_transcripts 滚动 messages
   - 无 transcript 时回退 sessions.context_summary
   - 若为审批恢复：按 run_id 加载 checkpoint
3. InputCompiler 编译用户输入 → CompiledInput
4. shouldQuery 门控
   - 否：写 turn.accepted + 本地完成事件，零模型调用，结束
   - 是：立即写 turn.accepted（保 TTFB），再进 AgentEngine
5. 写作场景可在此准备 system：素材卡 pin → cards.pinned 事件
6. 初始化 TurnState.messages，进入 AgentEngine.run
```

### 26.3 AgentEngine 单 Step 循环

```text
┌─ Step N ─────────────────────────────────────────────┐
│ 1. 检查 cancelled / cancel_force / 预算 / max_steps     │
│ 2. ContextEngine.assemble → ContextEnvelope            │
│    可发 context.reported（含 assemble_ms、分区、策略）   │
│ 3. 发 step.started                                     │
│ 4. ModelGateway.stream(GenerationParams + Envelope)    │
│    → turn.thinking / turn.token 增量事件               │
│ 5. 解析 assistant 输出                                 │
│    - 无 tool_use → final → turn.completed，break       │
│    - 有 tool_use → 进入 ToolExecutor                   │
│ 6. 工具：只读可并行；写/exec 串行；可能 approval 挂起   │
│    → tool.started / tool.delta / tool.completed        │
│ 7. tool_result 回灌 messages（先过 budget 截断）       │
│ 8. checkpoint；可选 step.completed                     │
│ 9. 发 usage.reported（可含 retry_count、cache 字段）   │
└──────────────────────────────────────────────────────┘
```

### 26.4 收尾

1. TurnController 落 transcript、更新 runs/turns 终态与 `termination_reason`。  
2. **api** 消费终态事件：投影补算、`sessions.context_summary`、评估采样等。  
3. runtime **不**在主路径同步做重投影、全量记忆重建、索引更新。

### 26.5 InputCompiler 输入类型细表

| 输入类型 | 处理 | 示例 |
|----------|------|------|
| 纯文本 | 进入 user content；多目标时可选注入一行计划弱提示（不强制 `update_plan`） | 「请改第二节」 |
| Slash 命令 | 确定性解析，非 LLM | `/help`、`/compact`、`/version`、`/verify` |
| `@path` 引用 | 文件指针块；预算内可预读，超时降级为纯指针；路径进入 `hot_files` 候选 | `@sections/02.md` |
| 附件 | 元数据 + `/data` 或 workspace 路径引用 | PDF、图片 |
| 选区上下文 | 编辑器 `selection` 块 | 写作改选中段 |

### 26.6 shouldQuery 短路细表

| 条件 | 行为 | 典型事件 |
|------|------|----------|
| 空消息 | 拒绝或友好提示 | — |
| `/help`、`/version` | 静态文本 | accepted → completed |
| `/compact` | 触发压缩任务并确认 | 同上 |
| `/verify` | **无模型**确定性扫描草稿/导出中的 cite 与路径引用；写报告；不改草稿 | accepted → completed |
| 未配置 model key（dev） | 明确失败 | failed |

实现必须是**可单测的规则表**，禁止用 LLM 做门控。  
`/verify` 结论字段直觉：`checked`（核对次数）、`invalid`（对不上的条数）；代表「引用能否指到资料文件」，不代表史实已人工审过。

---

## 27. 机制级深潜：性能与复杂度硬约束

吸收旧项目教训后的强约束；违反即架构回归。

### 27.1 默认最短主路径

主路径只允许：输入编译、上下文组装、模型调用、工具执行、终止判断、事件输出、checkpoint 与最小持久化。

**不得阻塞主路径**：记忆写回、检索索引更新、评估采样、通知推送、历史全量补算、非必要统计聚合。

### 27.2 默认最小状态集

除 `messages`、`step_count`、预算、取消位等少量控制字段外，禁止扩大运行时状态面。

尤其禁止：

- 工具内部中间态长期塞进 TurnState；  
- UI 结构塞进 execution state；  
- 「也许以后用得上」的大量空字段。

### 27.3 默认错误边界前置

必须优先在这些位置失败：command schema、tool schema、path sandbox、approval gate、provider 鉴权、budget 上限。  
禁止拖到 loop 深处才暴露，让模型「猜为什么失败」。

### 27.4 长会话是常态假设

运行时必须假设：会读很多文件、跑很多工具、经历长链路、发生中断与恢复。  
因此 ContextEngine 的 budget/compact/collapse **不是优化项，而是生存机制**。

### 27.5 热/温/冷上下文策略

| 层 | 内容 | 保留方式 |
|----|------|----------|
| 热 | 当前几轮相关消息、最近工具结果、当前约束 | 优先原文 |
| 温 | 阶段性结论、文件摘要、验证结果 | 结构化摘要 |
| 冷 | 久远历史、完整日志、大块输出 | 指针与可重读引用 |

规则：大输出不应长期留在热上下文；子 agent 只能带回必要结论；治理优先保证当前目标完成率，而非机械保留更多历史。

---

## 28. 机制级深潜：工具系统全景

### 28.1 能力即工具

旧项目把 retrieval / verify / writing 做成流水线节点；新平台里它们都是工具，由模型在循环中按需调用。  
**加一个能力 = 注册一个工具，不动循环、不改图。**

### 28.2 ToolSpec 概念字段

工具规格至少包含：`name`、`description`、`input_schema`、`side_effect`、`approval`、`required_role`、`timeout_s`、异步可流式 `handler`。

要点：

- `description` 与 `input_schema` 是 prompt 的一部分，要当产品文案写；  
- handler 支持 async 与流式；  
- 结果进 messages 前必须过预算控制；  
- 对运行时友好：避免单次调用把系统拖入高成本状态。

### 28.3 工具性能约束

1. **默认按需暴露**：不把所有工具每轮完整暴露；可按角色/场景/agent 类型裁剪。  
2. **默认结果可截断**：大文件、海量搜索、长命令输出截断后保留指针/范围/摘要。  
3. **错误靠入口**：schema、越权、审批、超时、配额优先失败。  
4. **默认可观测**：至少记录 tool_call_id、tool_name、trace_id、latency_ms、status、approval_result、retry_count。

### 28.4 权威工具命名表

| 权威工具名 | 类别 | 说明 |
|---|---|---|
| `read_file` | core | 读文件 |
| `list_dir` | core | 列目录 |
| `glob` | core | 独立工具，不是 list_dir 别名 |
| `grep` | core | 文本搜索 |
| `propose_patch` | core write | 生成可审 diff，不直接落盘 |
| `apply_patch` | core write | 接受提议并落盘 |
| `write_file` | agent write | 整体新建/覆盖 |
| `edit_file` | agent write | 精确替换片段 |
| `run_command` | agent exec | 执行命令并流式返回 |
| `run_tests` | agent exec | 测试类执行 |
| `search_sources` | retrieval | 文档/资料检索（热路径不建索引） |
| `search_codebase` | retrieval | 代码库检索；早期可退化 grep+小索引 |
| `search_records` | retrieval | 多表/结构化召回；**当前 stub**（未接真实业务表） |
| `check_citation` | writing | 引用核对 |
| `update_outline` | writing | 大纲更新 |
| `draft_section` | writing | 按节起草 |
| `export_document` | writing | 导出 |
| `remember` / `recall` | memory | 按需偏好/约定记忆；独立仓；**禁止**每轮盲召 |
| `delegate` | delegation | 派生子 agent（`context_refs` + `hot_files` 指针） |
| `update_plan` | planning | 更新计划投影；未完成项可回填会话 `open_items` |

场景 Profile 的 `tool_names` **只能登记权威名**；别名不得进入新 schema。

### 28.5 工具返回结构建议

统一倾向：`summary`、`payload`、`artifacts`、`is_truncated`、`retry_hint`。  
目的：模型稳定消费、前端统一卡片、debug 区分摘要/正文/产物。

### 28.6 流式工具规则

`run_command`、长网络请求、持续 stdout 类工具：

- 过程进 `tool.delta`；  
- 最终摘要进 `tool.completed`；  
- 前端可看过程，messages 只回灌必要摘要。

---

## 29. 机制级深潜：副作用分级与审批流

这是旧 `policy_node` / `human_review_node` 的替代：**审批绑定到单个工具调用**，不是图终态节点。

### 29.1 分级表

> **设计口径 vs 实现口径**：架构专文用 `read/write/exec/network/delegate` 分级叙事；当前 runtime 实现核心是 `ToolSpec.requires_approval` + `ON_WRITE_TOOLS` 集合，再由 ScenarioProfile `approval_overrides` 覆盖。下表保留设计叙事，并注明代码默认。

| 级别 | 含义 | 示例 | 设计默认审批 | 代码侧备注 |
|---|---|---|---|---|
| `read` | 只读 | read_file、grep、glob、search_codebase | never | 通常 `requires_approval=False` |
| `write` | 改工作区/文稿 | propose_patch、draft_section、write_file | on_write | `ON_WRITE_TOOLS`；agent Profile 可将 write_file/edit_file 设为 always |
| `exec` | 执行命令/代码 | run_command、run_tests | always | run_command 需审批；agent Profile 将 `run_tests: never` |
| `network` | 外网/检索 | search_sources | 设计上偏谨慎 | **当前 search_sources 默认可直接调用**（无强制审批） |
| `delegate` | 子 agent | delegate | always | `requires_approval=True`；深度上限 `MAX_DELEGATE_DEPTH=2` |

### 29.2 审批时序

```text
模型产出 tool_use
  → ToolExecutor 查 approval 策略
  → 发 approval.requested
  → loop 挂起，Turn=waiting_approval，Run=interrupted
  → 用户 ApproveToolCall / DenyToolCall
  → allow：从同一 run_id checkpoint 继续执行
  → deny：回灌 ToolResult denied，模型改道
```

规则：

- exec/write 必须走路径白名单与隔离；  
- 拒绝记入 permission_denials；  
- 高风险授权不得仅靠模型自判断；  
- Web 上「批准/拒绝」与「Stop」产品语义分离。

### 29.3 只读并行 vs 写串行

Harness Tools 面：同一 Step 内多个只读 `tool_calls` 可并行，降低墙钟；写/exec 仍串行，避免竞态与难回滚副作用。

---

## 30. 机制级深潜：上下文引擎契约与多层防线

### 30.1 何时跑

`ContextEngine.assemble(state)` 在**每一轮 Step 调模型之前**执行。不是一次性治理阶段。

### 30.2 输入最小面

- TurnState.messages、step_index、ScenarioProfile  
- 当轮可见 ToolSpec 列表  
- session_context / project_context / runtime_context  
- ContextBudgetPolicy

### 30.3 输出 ContextEnvelope

概念字段：

- `system_blocks`：仅当轮模型调用，**不回写** TurnState.messages  
- `message_window`：可直接送模型，不再二次拼接  
- `included_tools`：与真实可见工具一致，供日志对齐  
- `budget_report`：压缩前后 token 估计、策略名、截断计数  
- `compaction_trace`：策略摘要与引用，不复制大段原文  
- 以及 project_context / runtime_context 等分区

### 30.4 多层防线顺序

```text
取消息窗口
→ apply_tool_result_budget          # budget
→ microcompact_tool_results         # 局部降噪
→ collapse（fill ≥ 0.80）           # 折叠工具历史
→ snip（fill ≥ 0.90）               # 丢最旧消息组
→ autocompact（fill ≥ 0.95）        # 整体摘要兜底
→ 调模型
```

| 策略 | 触发 / 直觉 |
|------|------|
| budget | 工具结果超字符预算则截断并保留指针 |
| microcompact | 先整理局部高噪音工具结果 |
| collapse | fill≥0.80：多工具历史→紧凑视图+指针 |
| snip | fill≥0.90：丢弃最旧消息组直至低于阈值 |
| autocompact | fill≥0.95：整体摘要；可走独立 summarizer（compact_timeout 默认 20s） |

### 30.5 填充率驱动的会话压缩阈值

设计默认值与代码一致：session transcript 滚动；填充率 **≥0.80 collapse → ≥0.90 snip → ≥0.95 autocompact**。  
**禁止**未达阈值就自动整窗摘要。

### 30.6 上下文性能约束

- 整理成本必须小于不整理带来的模型成本；  
- 默认优先最近轮次、高价值证据、当前任务约束；  
- 不能每轮重型全历史总结；  
- 压缩必须可解释；  
- 输出尽量稳定，降低模型抖动。

---

## 31. 机制级深潜：Cancel / Interrupt / Resume 权威语义

### 31.1 三类用户动作不可混称

| 用户动作 | 系统机制 | Turn 终态？ | 继续方式 |
|----------|----------|------------|----------|
| Stop / 取消本轮 | CancelTurn | 是 → cancelled | 同 Session **新发 Turn**；**无 ResumeTurn** |
| 审批工具 | Approval interrupt | 否 → waiting_approval | Approve/Deny 续**同一** Run |
| 拒绝写作 diff | PatchReject | 通常 Turn 已 completed | 新 Turn 或模型再改；非执行暂停 |

### 31.2 CancelTurn 软/硬

命令概念：`{ "reason": "user_requested", "force": false }`

| | force=false 默认 | force=true |
|--|------------------|------------|
| 模型流式 | 下一 abort 检查点断连；目标流式 Cancel ≤500ms P95 | 立即断连 |
| 工具 | 优雅收尾（默认约 500ms）后停 | 立即 kill；run_command 用 process group |
| 副作用 | 已落盘不回滚；半写按工具事务边界 | 同左 |
| 事件 | turn.cancelling 可选 → turn.cancelled | 同左 |

**禁止**仅在 Step 边界检查取消。

### 31.3 取消检查点清单

runtime 必须在以下位置轮询取消位：

1. ContextEngine.assemble 入口  
2. ModelGateway.stream — 每 100–200ms 或每 N token  
3. ToolExecutor — handler 入口、流式循环、exec 子进程  
4. delegate 子 AgentEngine — 与父 Run 共享 abort；父 cancel **级联**子任务（委派深度设计上限约 ≤2）  
5. Step 边界作兜底  

另：Cancel 必须能打断 **重试 backoff sleep**、assemble、预读 I/O。

### 31.4 取消双通道

并行生效，取先到达者：

1. Domain 标志：api 写 `runs.cancel_requested_at` + `cancel_force`；runtime 轮询  
2. 内部命令：`POST /internal/commands/cancel-turn`

### 31.5 Resume 边界

- Cancel 后 Run 终态 cancelled，**不可**恢复同一 Run。  
- 继续对话 = 新 turn_id + 新 run_id；记忆靠 transcript / context_summary。  
- 仅审批 interrupt 用 Approve/Deny 从 checkpoint 恢复同一 run_id。

### 31.6 写作 patch 与执行态

`propose_patch` 后若模型无后续 tool，Turn 正常 **completed**；用户在 Turn **结束后** accept/reject。  
**不**引入 `waiting_patch_decision` 执行态。

---

## 32. 机制级深潜：三层超时与 Stall Watchdog

Cancel 解决「用户主动停」；超时解决「外部依赖 hang」。

### 32.1 三层超时默认值

| 层级 | 默认上限 | 触发 | 典型终止 |
|------|----------|------|----------|
| Model 调用 | 120s | ModelGateway 单次 stream/complete | turn.failed，reason=model_timeout |
| 工具 | ToolSpec.timeout_s，默认 60s | ToolExecutor | tool.completed(status=timeout)，模型改道或终态 |
| Step 墙钟 | 300s | 自 step.started 起未完成 | turn.failed，reason=step_timeout |

规则：

- Model 超时必须断开 provider，禁止无限 await；  
- Step 墙钟覆盖 model+tools 合计，与 max_steps 正交；  
- cancel 与 timeout 并行时，cancel 优先则终态 cancelled；  
- Harness 另强调**首字节快超时**，避免「第一次就干等满 120s」。

### 32.2 Stall Watchdog

周期扫描活跃 Run（默认约每 30s）：

```text
条件：status ∈ {running, interrupted}
  AND 最新 turn_events.ts 早于 now - stall_threshold
  AND 无 cancel_requested_at
动作：日志 stall_detected + metric；可选 auto_fail
```

| 参数 | 默认 |
|------|------|
| stall_threshold | 120s 无新事件视为卡住 |
| stall_auto_fail | Phase 1 默认 false，仅告警 |

### 32.3 max_steps 与 token 预算

| 杠杆 | 默认直觉 |
|------|----------|
| max_steps | writing 约 40；agent 约 50；Profile 可配 |
| token budget | Turn 级硬顶；触顶 budget_exceeded |
| 工具结果截断 | 必做 |
| shouldQuery 短路 | meta 输入零模型调用 |

终止原因示例：`final` | `max_steps` | `cancelled` | `budget_exceeded` | `fatal_error` | `model_timeout` | `step_timeout`。  
注意：`max_steps` / `budget_exceeded` 可以是**可解释完成/截断**，不一定等于 failed。

---

## 33. 机制级深潜：Agent Harness 六面、分期与铁律

### 33.1 命名

早期「Model Harness」仅模型外围；现「Agent Harness」为六面总纲；Model 为子轨。

### 33.2 六面与主链路位置

```text
TurnController
  → Intake（InputCompiler / shouldQuery）     ← Intake
  → ContextEngine.assemble → ContextEnvelope ← Context（assemble_ms）
  → Model：GenerationParams + Gateway.stream ← Model（首 token / retry）
  → Tools：串行写 | 并行只读                 ← Tools
  → Guard：abort / timeout / watchdog        ← Guard
  → Proof：events + golden + SLO             ← Proof
AgentEngine while 语义冻结
```

### 33.3 Model 面 AH1 细节

已落地能力概念（与 `settings.py` / `ModelGateway` 默认值对齐）：

- 统一重试：**仅尚未吐出任何 stream item** 时重试瞬态错误；一旦已 emit 再失败 → Fatal，不再重试；  
- `model_max_retries=2`（最多 3 次尝试）；backoff 基 0.5s、上限 8s，且 sleep 可被 Cancel 打断；  
- 首字节快超时默认 **15s**，connect **10s**，整段 model 墙钟 **120s**；  
- 错误分类：ModelTransientError / ModelFatalError / ModelProviderTimeout；  
- GenerationParams：max_output_tokens 默认对齐 output_reserve（16384）、writing temperature 0.3、tool_choice=auto、thinking 默认关。

失败路径终态 **不得**伪装成 completed。

### 33.4 AH2 Prompt Cache

- 稳定前缀：system + 工具定义 + pinned 卡打 cache_control；  
- assemble 保证可缓存前缀跨 Step/Turn **字节稳定**，易变内容后置；  
- usage 报告 cache 读写 / hit。

### 33.5 AH3 / AH4 / AH-obs

| 分期 | 内容 |
|------|------|
| AH3a | Envelope 分区、assemble 复用、assemble_ms |
| AH3b | @path 预算预读；超时降级指针 |
| AH3c | 只读 tool_calls 并行；description hygiene |
| AH4 | autocompact 独立小模型+独立 timeout；token 估计估高且便宜 |
| AH-obs | retry_count、cache、assemble_ms 进事件契约；UI 面板可后置 |

排序纪律：**先稳 → 先 cache → 再加厚上下文**，避免性能倒退窗口。

### 33.6 体验 SLO 与热路径成本

| 指标 | 目标 P95 |
|------|----------|
| TTFB turn.accepted | ≤ 300ms |
| 首模型 token | ≤ 800ms |
| 流式 Cancel | ≤ 500ms |
| 长会话 | 50 Turn 后无明显线性恶化 |

| 成本项 | 约束直觉 |
|--------|----------|
| assemble_ms | 软上限；预读超时降级 |
| 输入 token 增量 | 硬上限；优先 cache 抵消 |
| 重试墙钟 | ≤ model_timeout_seconds |
| tokenizer | 估高优于估低；禁止每步重跑重型 tokenizer |
| compact 额外调用 | 独立 timeout/budget |

### 33.7 六条铁律

1. 受理优先  
2. 快失败  
3. 可打断压倒可靠  
4. 加厚必先能抵消  
5. 可测才算数  
6. 策略不进引擎分叉  

### 33.8 Harness「不是」清单

- 改写 while / 终止条件语义；  
- 恢复 13 节点或意图分类或强制 retrieval/verify；  
- 引擎内 if scenario 塞策略；  
- 每 scenario 复制 gateway；  
- 业务编排塞回 LangGraph；  
- 为省延迟：流后重放、跳过审批、静默截断未标记；  
- 未落地宣称完全对齐。

### 33.9 延后项与已落地补充

**仍延后**：多 provider failover、GatewayRegistry+pg_notify、JSON mode 等。

**已不再延后（相对早期草案）**：

- **阶段收缩工具表**：交付成功或步数偏晚时，从本步 tools JSON 拿掉 `search_sources` / `delegate` / `remember` / `recall` 等，减空转与 schema token；  
- **工具参数 JSON Schema 预校验**：不合规则返回 `invalid_arguments`，handler 不执行；  
- **compact 可分流小模型**（配置 `COMPACT_MODEL_*`，失败回退确定性摘要）；  
- **打字预热**：输入 debounce 后预热 embedder + 索引 load，不进 Turn 临界区；  
- **Guard 加厚**：egress allowlist、出站/日志 PII 正则脱敏、写文件/导出前 secret 扫描（短预算）。

---

## 34. 机制级深潜：事件 envelope 与 SSE 拉取模型

### 34.1 为何 Pull 而非 runtime 推浏览器

- runtime 不暴露公网；  
- 事件事实落库，可 replay、可对账；  
- api 独占 SSE，投影同进程消费通知。

### 34.2 触发机制

1. turn_events INSERT 后 DB NOTIFY；  
2. api LISTEN，投入队列；  
3. SSE 与 projection 消费；  
4. 空闲时约 300ms 轮询兜底，防 NOTIFY 丢失。

### 34.3 事件 envelope 概念字段

`event_id`、`stream_id`、`sequence`、`type`、`turn_id`、`run_id`、`step_index`、`trace_id`、`causation_id`、`ts`、`payload`。

规则：

- sequence 单 turn 严格递增；  
- 增量输出，禁止每步完整大快照；  
- 大内容进 artifacts，事件只带引用摘要；  
- 前端只消费事件与 projection，不本地发明执行事实。

### 34.4 常见事件类型族

| 族 | 示例 |
|----|------|
| Turn 生命周期 | turn.accepted、turn.cancelling、turn.cancelled、turn.completed、turn.failed |
| 流式 | turn.thinking、turn.token |
| Step | step.started、step.completed |
| 工具 | tool.started、tool.delta、tool.completed |
| 审批 | approval.requested |
| 改稿 | patch.proposed |
| 写作 | outline.updated、section.draft.delta、cards.pinned |
| 子 agent | subagent.started、subagent.completed |
| 可观测 | context.reported、usage.reported |
| 交付 | tool.completed / turn.completed 可含 delivery_status |

### 34.5 四层协议再强调

Resource / Command / Event / Projection：命令改变世界，事件记录事实，投影服务 UI。

---

## 35. 机制级深潜：Session 连续性与长会话

### 35.1 Turn 结束后

```text
runtime append 终态事件
  → UPSERT session_transcripts（滚动 messages）
  → api 异步更新 sessions.context_summary（薄摘要，UI/兜底）
新 Turn
  → 加载 transcript + 本条用户消息
满窗
  → ContextEngine 按 fill 阈值加重压缩
强制
  → /compact 写摘要并重置 transcript
```

### 35.2 工作区与数据

| 路径 | 内容 |
|------|------|
| /workspace | 用户文稿与任务文件；bind mount，可备份 |
| /data | artifacts、向量库、模型缓存等 |
| PostgreSQL | Turn 历史、事件、配置；重装栈不丢会话需卷+DB 备份 |

### 35.3 可靠性表

| 风险 | 策略 |
|------|------|
| runtime 崩溃 | checkpoint + 已写事件；恢复或标 failed |
| api 重启 | SSE 重连 replay；api 无状态 |
| projection 落后 | 以事件为准；可全量重建 |
| 重复提交 | client_request_id 幂等 |
| 审批中断 | checkpoint；Approve 按 run_id 恢复 |

### 35.4 升级纪律

- DB migration 版本化；  
- 事件 schema 版本化，旧事件可 replay；  
- Profile YAML 变更只影响新 Turn，不破坏进行中 Turn。

---

## 36. 机制级深潜：写作交付数据模型与 RAG 栈细节

### 36.1 事故为何重要

曾出现：Turn completed、对话总结正常，但 export 是提纲+占位+无关大文档拼接；真稿在 revisions，用户打开的 export 不对；sections 与 eval 残留混目录。

启示：**loop 正确 ≠ 交付正确**。

### 36.2 修复后的权威目录语义

```text
workspace/
├── outline.md
├── sections/{section_id}.md                    # 已确认正式稿
├── .agent/revisions/{turn_id}/{section_id}.md # 本轮草稿
├── .agent/turns/{turn_id}/manifest.json       # 本轮草稿清单
├── sources/                                   # 资料原文
├── sources/cards/                             # 素材卡（可不进向量索引）
└── exports/{name}.md                          # 显式章节集合导出
```

导出规则：

- `export_document` 强制有序 `section_ids`，**禁止**全目录通配；  
- `source=confirmed` 只读指定正式章节；  
- `source=current_draft` 只读当前 Turn manifest 指向的草稿；  
- 缺章或空章：**不写半成品**，`delivery_status=failed`；  
- UI 必须区分「执行完成」与「交付异常」。

### 36.3 eval 工作区隔离

eval 默认使用独立 `.eval-workspace`，每 case 重置；日常 `workspace/` 默认拒绝作为 eval 目录，防止测试垃圾污染用户稿。

### 36.4 RAG 检索栈细节

| 能力 | 说明 |
|------|------|
| 结构切块 | 按 # / ## / ### 切分，保留 section_title、行号；节过长再约 400/80 字符滑窗；跳过 paste-debug 与 cards 路径 |
| 真 hybrid | BM25 + 向量双路，RRF 融合；禁止「向量有结果就忽略关键词」 |
| 两级召回 | 文档摘要通道与 chunk 通道可并行；超时降级 chunk-only |
| lexical rerank | 提升专名/标题排序；cross-encoder 默认关 |
| 检索预算 | 每 Turn search_sources 默认 ≤3；重复 query 缓存并提示 |
| 结果瘦身 | excerpt 默认约 200 字；低分 hint 引导 read_file |
| 索引 | **查询路径永不 sync 全量索引**；上传/变更走异步 worker + 状态轮询；可选 `RETRIEVAL_BACKEND=pgvector` |
| 降级 | 空索引 keyword 文件系统兜底 + `index_lag` 提示；hash embedding 保证无重模型也能跑通契约 |
| 引用核对 | Turn 内 evidence 集合；文中 cite 不在集合可标 `unverified`；用户 `/verify` 扫磁盘草稿（含中文 cite id） |

### 36.5 素材卡设计细节

| 阶段 | 做什么 | 性能 |
|------|--------|------|
| 导入/人工维护 | sources/cards/ 放人物卡、情节摘要、风格卡 | 不占 Turn |
| 写作 Turn | 按用户消息选相关短卡 pin 进 system；默认合计 ≤2k 字 | 无额外工具轮次 |
| RAG | 只检索原文场面/细节；cards **不进**向量索引 | 少噪声、少重试 |

卡片可用 frontmatter：`kind: character|plot|style`。  
优先级：**pinned 卡 > 用户当轮要求 > search_sources 素材**。

UI 观测：

- 活动条「本轮写定：…」；  
- 右侧产物栏列出 kind/标题/路径；  
- 无卡时提示库中是否有卡、是否未自动选中。

### 36.6 观测误报教训

若诊断仅用关键词「资料」判断必须 search_sources，则「你对资料库有什么理解？」类元问题会被误报「未检索」。  
正确方向：元问题 `not_needed`；明确引用请求才强制检索路径。  
**观测层不得扭曲执行层事实。**

---

## 37. 机制级深潜：Web 工作台契约

### 37.1 技术形态

Vite + React + TypeScript；生产多阶段构建为静态资源，nginx 托管；**禁止**生产常驻 Node。  
API 基址用相对路径 `/api/v1`，经 gateway 反代。

### 37.2 原则

1. 不猜阶段：SSE + TurnView；  
2. 按 scenario 换布局：writing vs agent；  
3. 共享 realtime 层：cursor、重连、乐观 Stop；  
4. 写作编辑器焦点优先；Agent 时间线可折叠。

### 37.3 Stop 交互时序

```text
T+0ms  立即冻结本地渲染（token / thinking.delta / tool.delta / draft.delta 不再 append）
T+0ms  「正在停止…」；思考块冻结为「思考过程」
T+0ms  POST cancel（默认 force=false）；SSE **继续**消费终态
T+?    turn.cancelled → 对齐终态（非 failed）
T+~500ms 仍 running 时可升 force
```

| TurnView.status | 主操作 |
|-----------------|--------|
| running | Stop → CancelTurn；取消 ≠ model_error |
| waiting_approval | 批准/拒绝；非与 Stop 混用 |
| cancelled | 可发新消息＝新 Turn；忙时队列可在空闲后合并发出 |

**禁止**等 turn.cancelled 才停 UI。  
**禁止** stopRendering 掐死整条事件流（否则 busy 只能靠定时器）。  
忙时 composer 可排队，空闲合并成下一 Turn（见 `10` §5.1.1）。

### 37.4 模型供应商设置

Web 设置页管理 provider profile：密钥脱敏展示；提交到 api→DB；Turn 边界热生效，无需重启 runtime。  
禁止前端存明文 API key。

---

## 38. 机制级深潜：Golden 用例族与断言形态

### 38.1 一条 Golden 是什么

固定：scenario_id、fixtures 工作区、input message、model_mode、assertions。

断言可覆盖：

- 事件序列包含/不包含；  
- turn status；  
- workspace 文件内容；  
- 延迟门禁字段；  
- 工具是否被调用。

### 38.2 model_mode

| 模式 | 用途 |
|------|------|
| stub | 确定性假模型，保管道与工具路径 |
| recorded | 录制回放，保复杂交互回归 |
| live | 真供应商烟雾；不应用抖动掩盖契约失败 |

### 38.3 能力融合阻断项

| 能力 | 证明 |
|------|------|
| ContextEngine | 大输入触发 budget/compact，策略名可观测 |
| RAG writing | search_sources → tool_result → 成稿引用路径 |
| RAG agent | search_codebase 被调用且进 timeline |
| 多 agent | delegate → subagent 起止 → 主 Turn 完成 |

另有管道类：patch accept/reject、cancel 中流/中工具、shouldQuery help、导出范围、hybrid 专名召回等。

### 38.4 分层验证命令直觉

smoke → eval-all → eval-retrieval → eval-queue → runtime/api/web 单测 → live 夜间。  
Eval **不**阻塞主路径执行。

---

## 39. 机制级深潜：配置、模型热生效与部署剖面

### 39.1 配置

- 十二要素：环境变量 + Settings；  
- `.env` 为入口；服务内禁止再堆第二套巨型 YAML 真相源；  
- compose 单一入口；queue / retrieval / ha 等为**可选 profile**，不是必记 overlay 咒语。

### 39.2 模型热生效

Web → api 写 DB profile → runtime 在 **Turn 边界**读取激活配置。  
好处：换 key/模型不必重启整栈；整轮 Turn 内配置固定，避免半轮漂移。

### 39.3 部署剖面直觉

| 剖面 | 增强 |
|------|------|
| 默认 | 最小可跑；检索可 hash 降级 |
| retrieval | 本地 embedding 模型烘焙、向量索引增强 |
| queue | outbox worker 异步索引等 |

健康检查：`healthy` **不等于** embedding 已热；首次索引仍可能冷启动——上传必须异步+可轮询状态。

---

## 40. 机制级深潜：反模式清单与设计否决案

### 40.1 明确反模式

1. 恢复 13 节点或任意固定大图承载业务；  
2. 每轮预塞向量包；  
3. 独立 retrieval/context 模块从不被 loop 调用；  
4. 子会话全量倒灌主 messages；  
5. 引擎内 if scenario 业务分支；  
6. 为每场景复制 loop/事件管线/runtime；  
7. runtime 直接对浏览器 SSE；  
8. 仅内存 channel 作跨服务唯一事件源；  
9. 仅 Step 边界检查 cancel；  
10. UI 等终态才停渲染；  
11. 静默覆盖用户未审文稿；  
12. export 通配整个 sections 目录；  
13. Turn completed 却无 delivery_status 区分产物失败；  
14. 用关键词诊断覆盖真实工具路径；  
15. 把 LangGraph 业务编排当卖点宣传；  
16. 未落地宣称「已完全对齐 Cursor」。

### 40.2 曾被否决的备选

| 备选 | 否决原因 |
|------|----------|
| 维持单体 | 重复技术债 |
| 细分为 10+ 微服务 | Phase 0 过度设计 |
| 原样 port 13 节点 | 违背重写初衷 |
| 默认 loop + 大量固定 workflow 混核 | 早期不需要，易回流旧债 |
| 纯裸 while 且无机制层 | 放弃现成 checkpoint/interrupt；可保留薄机制壳 |
| 通用 Pause/ResumeTurn | 与 Run:Turn 1:1 冲突，状态机膨胀 |
| patch 等待新状态 waiting_patch | 不必要扩展状态机 |

---

## 41. 机制级深潜：端到端用户旅程

### 41.1 写作：资料成稿改稿导出

```text
用户进入 writing 场景
  → 资料已在 sources/；可选维护 sources/cards/
  → 发：「根据资料写两章并导出」
  → turn.accepted 立即出现
  → cards.pinned 显示本轮写定
  → 模型可能 search_sources / draft_section / propose_patch / export_document
  → 用户在 diff 中 accept 改稿
  → 导出指定 section_ids；检查 delivery_status
  → 若中途 Stop：UI 立刻停；新消息开新 Turn
```

### 41.2 Agent：探索改文件跑命令

```text
用户进入 agent 场景
  → 发复杂任务
  → 时间线可见 read/glob/grep/search_codebase
  → 只读步骤可并行缩短等待
  → propose_patch 可审；run_command 先审批
  → 可 delegate explore/verify
  → Cancel 级联子 agent
```

### 41.3 长会话

多 Turn 后 transcript 滚动；达阈值压缩；必要时 `/compact`；50 Turn 后延迟不应线性崩坏。

### 41.4 供应商抖动

Model 面重试+快超时：短暂 429/5xx 少无意义整轮失败；Cancel 仍可打断等待；失败分类可区分「模型挂了」与「交付失败」。

---

## 42. 机制级深潜：给分析 AI 的抽取模板

请按下列 JSON 骨架抽取，缺失填 null 并注明「本文未给出」：

```json
{
  "one_liner": "",
  "legacy_root_causes": [],
  "structural_advantages": [],
  "scenarios": ["writing", "agent"],
  "loop_shape": "controller_plus_engine_while",
  "rag": {
    "style": "tool_mediated",
    "writing_tool": "search_sources",
    "cards": "pin_into_system_not_indexed",
    "hybrid": "bm25_plus_vector_rrf"
  },
  "context": {
    "per_step_assemble": true,
    "layers": ["budget", "microcompact", "collapse", "snip", "autocompact"],
    "fill_thresholds_pct": [80, 90, 95]
  },
  "multi_agent": {
    "mechanism": "delegate_tool",
    "return_mode": "summary_only"
  },
  "harness": {
    "name": "Agent Harness",
    "faces": ["Intake", "Context", "Tools", "Model", "Guard", "Proof"],
    "slo": {
      "ttfb_ms_p95": 300,
      "first_token_ms_p95": 800,
      "cancel_ms_p95": 500
    }
  },
  "cancel": {
    "no_resume_turn": true,
    "approval_resumes_same_run": true,
    "optimistic_ui_stop": true
  },
  "timeouts_s": {
    "model": 120,
    "tool_default": 60,
    "step": 300,
    "stall_threshold": 120
  },
  "delivery_honesty": {
    "explicit_section_ids": true,
    "delivery_status_required": true,
    "eval_workspace_isolated": true
  },
  "non_goals": [],
  "honest_gaps": [],
  "resume_bullets_suggested": [],
  "top_risks": [],
  "next_30_days": []
}
```

然后继续回答第一部 §24 的七个分析问题。

---

## 文末补记

第一部建立叙事与边界；第二部提供机制级可检验细节；**§43 给出与代码核对结论**。  
上传独立仓库时请**整文件保留**，不要只抽「亮点 bullet」而丢掉超时数字、反模式、交付数据模型、抽取模板与 §43——那些正是另一个 AI 做严肃分析时最需要的锚点。


---

## 43. 与代码仓库核对结论与仍可补充项

> 本节初版 **2026-07-13**；**2026-07-15** 对照 S0–S3 之后 `services/runtime` / `api` / `web` 与 Profile YAML 增量复核。  
> 目的：独立文档仓库读者与分析 AI 知道哪些断言已锚定实现，哪些是设计叙事，哪些仍可再补。

### 43.1 已与代码吻合的关键断言

| 断言 | 代码锚点 |
|------|----------|
| LangGraph 单节点机制壳，业务在 AgentEngine | `services/runtime/app/graph/runner.py` 仅 `agent_loop` 一节点 |
| writing max_steps=40，agent=50 | `scenarios/profiles/writing.yaml` / `agent.yaml` |
| model_timeout=120s，step_timeout=300s，tool_default=60s | `settings.py` |
| stall_threshold=120s，poll=30s，auto_fail 默认 false | `settings.py` + `stall_watchdog.py` |
| 首字节快超时 15s，connect 10s，max_retries=2 | `settings.py`；gateway 在未 emit 前才重试 |
| Cancel 可打断 backoff sleep | `ModelGateway._interruptible_sleep` |
| 只读工具并行、写工具串行 | `AgentEngine` tool 调度注释与实现 |
| fill 阈值 0.80/0.90/0.95 | `CompactionPolicy` / settings |
| search_sources ≤3/Turn，excerpt 200 字 | settings |
| cards 总预算 2000 字，单卡 800 | settings + `writing/cards.py` |
| hybrid = BM25 + vector + RRF；lexical rerank 默认开；cross-encoder 默认关 | `vector_index.py` / settings |
| 热路径 search 不 sync 全量索引；可选 pgvector；两级召回可开 | `tools/core/tools.py` `search_sources`；`two_level.py`；settings |
| 工具参数 JSON Schema 预校验（默认开） | `tools/validate.py` + `ToolExecutor` |
| 阶段收缩工具表（晚步/交付后丢 search/delegate/memory） | `bootstrap.stage_tool_scope` |
| `/verify` 确定性引用扫描；不改草稿 | `controller/verify_pass.py`；Intake `should_query` |
| remember/recall 按需记忆；写作/Agent Profile 已登记 | `tools/core/memory.py`；profiles |
| search_records 为 stub | `tools/core/records.py` |
| delegate context_refs + hot_files（≤12） | `delegate_runner` / `turn_controller._resolve_delegate_hot_files` |
| egress allowlist；出站/日志 PII 脱敏；写出 secret 扫描 | `model/egress.py`；`privacy/redact.py`；`privacy/secret_scan.py` |
| 打字预热 embed + store.load | web `useWorkbench` debounce 300ms → api → runtime `warmup-retrieval` |
| export 强制 section_ids；source=confirmed\|current_draft | `tools/bootstrap.py` export schema |
| delivery_status 进入完成事件 | `agent_engine.py` |
| delegate 深度上限 2 | `MAX_DELEGATE_DEPTH = 2` |
| run_command 优雅终止 grace=0.5s，force 用 SIGKILL | `tools/core/shell.py` `TERMINATE_GRACE_SECONDS` |
| SSE：NOTIFY + wait timeout 0.3s 兜底 | api `listener.py` / `events.py` |
| Web Stop 先 `stopRendering()` 再 POST cancel | `useWorkbench.ts` handleStop |
| apply_patch 落盘可由 accept_patch 命令触发 | `turn_controller.accept_patch` |
| 写作 Profile 含 search_sources/delegate/export/remember/recall…，不含 run_command/grep | `writing.yaml` |
| Agent Profile 含 glob/grep/run_command/write_file/search_records… | `agent.yaml` |

### 43.2 本次核对后已修正的文档偏差

| 偏差 | 修正 |
|------|------|
| 曾写压缩顺序 budget→snip→microcompact→collapse→autocompact | **改为** budget→microcompact→collapse→snip→autocompact（与 `ContextEngine` 一致） |
| 曾把 apply_patch 写成与 propose_patch 同级「模型工具主路径」 | **改为**写作侧用户 Accept 后走控制面 `accept_patch`；Profile 不暴露 apply_patch 给模型 |
| 副作用五级表易被读成「已完整实现枚举」 | **标明**实现以 `requires_approval` + overrides 为主；search_sources 当前默认可直接调用 |
| 曾把「动态裁剪工具表」列在 §33.9 延后项 | **改为**阶段收缩工具表已落地（见 §33.9） |
| RAG 节偏早期 | **补**热路径不建索引、可选 pgvector、两级召回、`/verify`、evidence（§11.4 / §36.4） |
| 工具权威表缺记忆与多表 | **补** `remember`/`recall`/`search_records(stub)`（§28.4） |

### 43.3 设计叙事与实现之间的软差异（不是错误，但分析时勿夸大）

1. **SideEffect 五级枚举**：专文完备；代码尚未用同名枚举贯穿一切，而是布尔审批 + 写工具集合。  
2. **SLO 数字**：TTFB≤300ms、首 token≤800ms、Cancel≤500ms 是产品目标与 golden 门禁取向；live 供应商路径受网络影响，stub 路径更易达标。  
3. **写作 patch 审阅 vs 工具审批**：`propose_patch` 默认不触发 `waiting_approval`；用户审阅在 Turn 完成后通过 UI Accept/Reject，落盘走 `accept_patch` 命令。  
4. **实时传输**：权威路径是 SSE + NOTIFY；Web 另支持可选 WebSocket（`?transport=ws`），不是第二套状态机。  
5. **AH2–AH4「核心路径已落地」**：代码确有 cache_control、assemble 复用/ms、@path 预读、只读并行、compact 独立 timeout、usage/context 字段；「细调与 golden 加固」仍可能继续。  
6. **ContextEnvelope 字段**：实现 dataclass 用 `system_prompt` 等字段；与专文 `system_blocks` 命名略有差，但分区意图一致。  
7. **事件类型全集**：文档列举族名；并非每个场景每次 Turn 都发射全部类型。  
8. **`/verify` 与「事实核查」**：证明引用锚点能否指到资料文件，**不**等于内容事实已被人审；`unverified` 默认不硬阻断交付。  
9. **企业万档 / 多租户 / 真多表**：前置能力（异步索引、ANN 可选、两级召回、records stub）在；ACL 与业务表未接——勿写成已交付。

### 43.4 仍建议补充、但非阻塞独立阅读的材料

若还要「更更细」，可另附或后续追加：

1. **事件 payload 字段级字典**：每个 `type` 的必选/可选字段与示例 JSON；  
2. **内部命令一览**：start-turn / cancel-turn / accept-patch / approve-tool / warmup-retrieval 等请求响应；  
3. **DDL 摘要**：turns/runs/turn_events/session_transcripts/model_provider_profiles 关键列；  
4. **Golden 全量 ID 清单**：writing.* / agent.* / shared.* / live.* 与断言焦点；  
5. **子 agent 角色→工具白名单表**：`delegate_runner` 内 researcher/explore 等映射；  
6. **失败分类决策树**：Transient vs Fatal vs Timeout 如何映射终态；  
7. **实测体感附录**：作者自用任务样本、延迟主观感受、与旧项目对比的定性记录。

以上 1–6 偏契约附录；7 偏产品证言。当前正文对架构分析已足够；缺的是「字段级 OpenAPI」与「个人用例日记」。

### 43.5 给分析 AI 的一致性指令

1. 数字与顺序冲突时：**以 §43.1 与 §30.4 修正后的实现顺序为准**。  
2. 不要把设计专文的 SideEffect 五级表描述成「代码已有同名类型系统」。  
3. 写作改稿请写成「propose → 用户审阅 → accept_patch 命令落盘」，不要写成「模型直接 apply」。  
4. LangGraph 仅机制壳；不要推断存在多节点业务图。  
5. 检索默认 hybrid + lexical rerank；不要写成默认启用 cross-encoder；搜索热路径不建索引。  
6. 实时传输默认 **SSE**；Web 可选 `?transport=ws` 走 WebSocket，事件形态与 SSE 对齐，非第二套业务语义。  
7. 阶段收缩工具表、schema 预校验、`/verify`、remember/recall、egress/脱敏/secret 扫描均已落地；不要仍写成「仅设计草案」。  
8. `search_records` 与企业万档 ACL 勿夸大为已接真实后端。

### 43.6 总评

- **总体吻合度高**：拆分、loop、Intake、事件拉取、Harness 超时/重试、上下文阈值、RAG 预算、素材卡、交付修复、delegate 深度、Web 乐观 Stop，均能在仓库找到对应实现。  
- **2026-07-15 增量**：schema 门、阶段缩 tools、`/verify`、按需记忆、Guard（egress/PII/secret）、检索热路径纪律与两级/pgvector 可选、delegate 指针传上下文——正文 §11/13/18/26/28/33/36 已对齐。  
- **已修正关键不一致**：压缩顺序、apply_patch 路径、审批分级表述、以及「动态裁剪仍延后」的过期说法。  
- **仍可补充**：偏契约字段字典与自用体感附录，不阻碍把本文当独立知识库使用。
