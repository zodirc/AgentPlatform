---
name: agent-writing
description: >-
  Enforces this repo's technical prose for tone, storage and Turn terminology,
  code comments, ADR versus tour docs, and main-chain flowchart PNGs. Use when
  writing or editing docs, ADRs, tour pages, comments, or when the user
  mentions 口吻, 名词, 注释, 文档, ADR, 导览, 流程图.
---

# 文档与注释

编写或修改本仓库的文档和代码注释时执行。先用下表的名词，再写流程。方案细节以对应 ADR 或执行文档为准，不在本 skill 里抄一份。

## 口吻

- 句子给出对象、动作和条件。不写宣传句，不解释项目名称。
- 中文正文用下表的名词。表名、函数、事件名、错误码、配置项用反引号照抄代码。
- 同一概念全文只用一个名词。服务器文档里的一次提问叫 Turn；写作客户端文档里同一次叫回合。一篇里不要混用。
- 数字和默认值从代码或配置读取。文档、ADR、图上的数字冲突时，以代码和 `packages/contracts` 为准，其次导览正文，最后才是图。

## 名词

| 使用 | 不使用 |
|---|---|
| Turn | 轮次（服务器文档） |
| 回合 | Turn 的口语（仅写作客户端与本地接头文档） |
| 会话 | 对话（指 `sessions` 行） |
| Work | 工作区（指 `works` 行）；本地接头文档用「作品」 |
| 耐久事件 | 持久事件、历史消息（指 `turn_events`） |
| 活流 | 实时流（指 `turn.live.*`） |
| 真源 | 主库（指 Turn 与 claim 所在的 Postgres） |
| 门铃 | 通知、推送（指只带 UUID 的 NOTIFY / Pub/Sub） |
| 热路径 | 主流程（指用户提问到首 token） |
| 旁路 | 后台（指不挡受理的异步活） |
| 组窗 | 拼 prompt |
| 投影 | 缓存视图（指 `turn_views` 等） |
| 租约 | 锁（指 `runs` 的 lease） |
| 接头 | host（指 `app/writing_host`） |
| 壳 | 前端（指 Web 或 Android 的界面层） |
| 终态 | 结束；`cancelled` 与 `failed` 分开写 |

`cancelled` 不是 `failed`。Redis 可丢、可重复，不能写成 claim 的依据。审批挂起后是同一 `run_id` 加 checkpoint 续跑，不存在 ResumeTurn。

## 代码注释

新增或改动锁、事务边界、失败后的状态、回收放弃条件时，在同一处写注释。没有这些边界的函数不补注释。

- 注释使用中文，名词与上表一致。
- 只写不变量、锁顺序、哪一步失败会留下什么、为什么放弃整轮。代码已经表达的动作不注释。
- 不在注释里重述 ADR 段落，不写待办口号。

## 文档放哪

| 种类 | 位置 | 写什么 |
|---|---|---|
| 决策 | `docs/adr/NNN-*.md` | 状态行、决策、机制。现状段只写代码的真实行为 |
| 导览 | `docs/tour/pages/*.html` | 现行路径：入口、调用点、状态变化。人类入口 |
| 客户端与内核方案 | 壳与接头的方案文档 | 现行约定。改行为时改对应句子 |
| 执行方案 | `docs/` 下已有的执行方案 | 阶段和验收。不在 ADR 里再排一份阶段 |

ADR 开头是 `# ADR-NNN 标题` 和 `状态：提议。` 或 `状态：已实施。`。状态与代码不符就改状态或改现状段，不保持过期的「已实施」。

导览页是 `<section class="page">`。步骤写调用点和状态，不把图上的句子再抄一遍。

## 流程图

`docs/assets/**/*.png` 的画法以 `.cursor/rules/docs-flow-diagram.mdc` 为准。样板以那份规则点名的图为准。本 skill 不重述那份规则。

禁止把 Mermaid、Graphviz、等重卡片、Unicode `↓` 脊柱，或在旧 PNG 上涂改的结果当作正文图。
