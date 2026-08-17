# 文档 Wiki

在线翻页（推荐）：https://zodirc.github.io/AgentPlatform/

左侧目录切章、不整页刷新；流程图加载过一次会留在浏览器里。本地同样：`make docs-tour` → http://127.0.0.1:8765/tour/

下面是 Markdown 原文目录。从 GitHub 文件视图点这些链接会整页刷新，图也会再下一次，适合对照源文件，不适合当 Wiki 翻。

对错：**代码与契约 > 本目录六篇正文 > 导览**。数字以 https://github.com/zodirc/AgentPlatform/blob/master/eval/official/baseline/RESULTS.md 为准。`plan/` 是可删草稿，不参与权威。

---

## 怎么读

图负责看清分支。正文负责说每一步在干什么。绿字/代码名只是事件或字段，不是流程本身。

建议顺序：一次提问怎么走 → 推理循环 → 编码或写作（按你关心的场景）→ 评测怎么计分。

---

## 总览

| 打开 | 读什么 |
|------|--------|
| [架构](core/architecture.md) | 浏览器、api、runtime 各干什么；runtime 自己来领活；符号表在旁路，不挡提问 |
| [图 · 请求主路径](assets/architecture/request-path-zh.png) | 点发送之后，请求怎么穿过网关落到推理 |
| [图 · 分模块发布](assets/ops/release-modular-deploy-zh.png) | 哪个容器脏了、怎么重建 |

（图点上面链接打开即可。目录页不再内嵌整张海报，避免每次进 Wiki 都重新拉 1.5MB+。）

---

## 一次提问

| 打开 | 读什么 |
|------|--------|
| [架构 · 领域对象](core/architecture.md) | 作品世界 / 聊天线程 / 点一次发送 / 真正在跑的实例 |
| [图 · 提问状态](assets/architecture/turn-lifecycle-zh.png) | 排队 → 运行 ⇄ 等待审批 → 完成或取消 |
| [事件与契约](core/events.md) | 落库、领取、取消、批准怎么当命令送达 |
| [图 · 启动命令链](assets/events/start-turn-command-zh.png) | 202 只表示记下了；「开始想」要等 runtime 领到活 |

---

## Runtime

| 打开 | 读什么 |
|------|--------|
| [Runtime](core/runtime.md) | 外壳管领活和收尾；循环管组窗 → 问模型 → 跑工具 |
| [图 · 推理循环](assets/harness/agent-engine-loop-zh.png) | 中间那条从上到下的箭头链 |
| [图 · 审批与取消](assets/harness/approval-cancel-resume-flow-zh.png) | 等人点头时执行实例还在；取消 ≠ 跑失败 |

---

## 工具 · 组窗 · 沙箱

| 打开 | 读什么 |
|------|--------|
| [工具与上下文](core/tools-and-context.md) | 能力就是工具；编码把「找定义、看波及、改完再验」写进返回值 |
| [图 · 组窗](assets/context/context-assemble-ladder-zh.png) | 每次问模型前怎么收拾窗口 |
| [图 · 沙箱](assets/sandbox/bwrap-exec-flow-zh.png) | 日常命令关在作品根；评测题的测试进该题 Docker |

---

## 编码

| 打开 | 读什么 |
|------|--------|
| [工具与上下文 §2](core/tools-and-context.md) | 读题 → 复现 → 找定义 → 改 → 再验；想交卷却还欠验证会再催一轮 |
| [图 · 写入链](assets/harness/coding-fuse-zh.png) | 查找 / 波及 / 验证焊进已有工具，不另发明导航工具名 |
| [工作台 · Agent](topics/workbench.md) | 编码工作台对照写作：同一套作品 → 会话 → 提问 |

---

## 写作 · 检索

| 打开 | 读什么 |
|------|--------|
| [RAG](topics/rag.md) | 要点「搜资料」才查；禁止每轮自动塞向量包 |
| [图 · 店内召回](assets/rag/search-sources-flow-zh.png) | 切块车道和文档车道并行，再融合 |
| [图 · 建库](assets/rag/index-sync-zh.png) | 建库在提问环外；切块大约 450 token、重叠 64 |
| [工作台 · 写作](topics/workbench.md) | 一本书；改稿走差异，每一遍都是用户自己点的发送 |
| [图 · 写作主路径](assets/writing/writing-main-path-zh.png) | 大纲 → 成稿 → 改稿；检索按需 |

---

## 事件

| 打开 | 读什么 |
|------|--------|
| [事件与契约](core/events.md) | runtime 只写事件行；api 再发给浏览器。界面不猜进行到哪一步 |
| [图 · 事件流](assets/events/event-sse-zh.png) | 追加 → 通知 → 实时流 / 列表快照 |
| [契约索引](contracts.md) | OpenAPI、事件 schema、评测清单 |

---

## 评测

| 打开 | 读什么 |
|------|--------|
| [工作台 · Ops](topics/workbench.md) | 效果温度计，不是合入门禁；必须走产品同一条提问路径 |
| [图 · Bench](assets/ops/ops-bench-principle-zh.png) | 检索 / 长文 / 编码四套件怎么接到真实工具 |
| [评测日记](../eval/official/baseline/RESULTS.md) | 现行冒烟数字。SCORECARD 机器栏不是最新 |

---

## 运维 · 草稿

| 打开 | 说明 |
|------|------|
| [Pull 分发手册](ops/pull-dispatch-runbook.md) | 领取、租约、队列满回 429 |
| [`plan/`](plan/README.md) | 落地前草稿，**可删**；不要当现行流程读 |

起栈见仓库根 README。图是 **主链详流**（样板：[StartTurn 命令链](assets/events/start-turn-command-zh.png)）：中间一条编号箭头链，左右是注。整张手绘 PNG；禁止脚本出图、禁止在旧图上涂改。
