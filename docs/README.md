# 文档 Wiki

在线翻页（推荐）：https://zodirc.github.io/AgentPlatform/

左侧目录切章、不整页刷新；图在首次加载后由浏览器与 Service Worker 缓存。本地：`make docs-tour` → http://127.0.0.1:8765/tour/

下列为 Markdown 原文目录。从 GitHub 文件视图打开会整页刷新并重复下载海报，适合对照源文件，不适合当 Wiki 阅读。

权威顺序：**代码与契约 > 本目录六篇正文 > 导览**。评测数字以 https://github.com/zodirc/AgentPlatform/blob/master/eval/official/baseline/RESULTS.md 为准。`plan/` 为可删草稿，不参与权威。

---

## 怎么读

图给出分层、分支与容量。正文给出职责边界、旋钮与失败语义。事件名与字段名是契约标识，不是流程图本身。

建议顺序：部署拓扑与后端栈 → 一次 Turn 的请求路径 → AgentEngine 循环 → 场景（编码或写作）→ 评测计分。

---

## 总览

| 打开 | 读什么 |
|------|--------|
| [架构](core/architecture.md) | 网关、api、runtime 的职责边界；pull 分发；符号表与评测在旁路 |
| [架构 · 容器 / 负载 / 并发](core/architecture.md#backend) | 四层栈、`depends_on`、NOTIFY/LISTEN、runtime 副本与 inflight |
| [图 · 后端栈](assets/architecture/backend-stack-zh.png) | 产品 / 控制 / 执行 / 数据面；启动、扩容与数据通道 |
| [图 · 请求主路径](assets/architecture/request-path-zh.png) | 受理 → 领取 → Engine → 事件 / SSE → Web |
| [图 · 分模块发布](assets/ops/release-modular-deploy-zh.png) | dirty 判定、分模块重建、如何确认已更新 |

（图点上面链接打开即可。目录页不再内嵌整张海报，避免每次进 Wiki 都重新拉 1.5MB+。）

---

## 一次提问

| 打开 | 读什么 |
|------|--------|
| [架构 · 领域对象](core/architecture.md) | Work / Session / Turn ↔ Run；取消 ≠ failed |
| [图 · 提问状态](assets/architecture/turn-lifecycle-zh.png) | pending → running ⇄ waiting_approval → 终态 |
| [事件与契约](core/events.md) | 落库、领取、取消、批准如何作为命令送达 |
| [图 · 启动命令链](assets/events/start-turn-command-zh.png) | 202 表示已入队；`turn.accepted` 发生在 runtime claim 之后 |

---

## Runtime

| 打开 | 读什么 |
|------|--------|
| [Runtime](core/runtime.md) | Controller 负责领取与收尾；Engine 负责组窗 → 模型 → 工具 |
| [图 · 推理循环](assets/harness/agent-engine-loop-zh.png) | assemble → model → tools；中间垂直主链 |
| [图 · 审批与取消](assets/harness/approval-cancel-resume-flow-zh.png) | 审批挂起仍持有同一 `run_id`；`cancelled ≠ failed` |

---

## 工具 · 组窗 · 沙箱

| 打开 | 读什么 |
|------|--------|
| [工具与上下文](core/tools-and-context.md) | 能力即工具；编码将查找、波及、验证写入既有工具返回值 |
| [图 · 组窗](assets/context/context-assemble-ladder-zh.png) | 每次调用模型前的窗口装配阶梯 |
| [图 · 沙箱](assets/sandbox/bwrap-exec-flow-zh.png) | 日常命令约束在 Work 根；官方评测测试进入该题 Docker |

---

## 编码

| 打开 | 读什么 |
|------|--------|
| [工具与上下文 §2](core/tools-and-context.md) | 读题 → 复现 → 查找定义 → 修改 → 再验证；欠验证时再催一轮 |
| [图 · 写入链](assets/harness/coding-fuse-zh.png) | 查找 / 波及 / 验证焊入既有工具，不另发明导航工具名 |
| [工作台 · Agent](topics/workbench.md) | 编码工作台对照写作：同一套 Work → Session → Turn |

---

## 写作 · 检索

| 打开 | 读什么 |
|------|--------|
| [RAG](topics/rag.md) | 仅在调用 `search_sources` 时检索；禁止每轮自动注入向量包 |
| [图 · 店内召回](assets/rag/search-sources-flow-zh.png) | 切块车道与文档车道并行，再融合 |
| [图 · 建库](assets/rag/index-sync-zh.png) | 建库在提问环外；切块约 450 token、重叠 64 |
| [工作台 · 写作](topics/workbench.md) | 单部作品；改稿走差异，每一遍由用户显式发送 |
| [图 · 写作主路径](assets/writing/writing-main-path-zh.png) | 大纲 → 成稿 → 改稿；检索按需 |

---

## 事件

| 打开 | 读什么 |
|------|--------|
| [事件与契约](core/events.md) | runtime 只追加事件行；api 负责 SSE / 投影。界面不得推断 Turn 阶段 |
| [图 · 事件流](assets/events/event-sse-zh.png) | INSERT → NOTIFY → SSE / 列表快照 |
| [契约索引](contracts.md) | OpenAPI、事件 schema、评测清单 |

---

## 评测

| 打开 | 读什么 |
|------|--------|
| [工作台 · Ops](topics/workbench.md) | 效果温度计，不是合入门禁；必须走产品同一条 Turn 路径 |
| [图 · Bench](assets/ops/ops-bench-principle-zh.png) | 检索 / 长文 / 编码套件如何接到真实工具 |
| [评测日记](../eval/official/baseline/RESULTS.md) | 现行冒烟数字。SCORECARD 机器栏不是最新 |

---

## 运维 · 草稿

| 打开 | 说明 |
|------|------|
| [Pull 分发手册](ops/pull-dispatch-runbook.md) | claim、租约、准入 429、扩容指标 |
| [`plan/`](plan/README.md) | 落地前草稿，**可删**；不参与现行流程 |

起栈见仓库根 README。控制流海报为 **主链详流**（样板：[StartTurn 命令链](assets/events/start-turn-command-zh.png)）：中间一条编号箭头链，左右为注。后端栈图是分层架构，不是逐步流程。整张重绘 PNG；禁止脚本出图、禁止在旧图上涂改。
