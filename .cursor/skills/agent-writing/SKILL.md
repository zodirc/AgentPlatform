---
name: agent-writing
description: >-
  Enforces this repo's technical prose: professional register, storage and
  Turn terminology, code comments, ADR versus tour docs, and main-chain
  flowchart PNGs. Sentences that constrain behavior are implemented in the
  same change. Use when writing or editing docs, ADRs, tour pages, comments,
  or when the user mentions 口吻, 名词, 注释, 文档, ADR, 导览, 流程图,
  专业化, 同步.
---

# 文档与注释

编写或修改本仓库的文档和代码注释时执行。先用下表的名词，再写流程。方案细节以对应 ADR 或执行文档为准，不在本 skill 里抄一份。

约束实现的句子与代码在同一次改动里保持一致。此类句子包括 ADR 的决策、执行方案、客户端与内核方案，以及导览中的现行路径。代码按这些句子实现，方法见 `align-change`。

## 口吻

文档供实现和审查使用。句子写完整，写明主体、条件、动作和结果。读者据此改代码或核对行为，不必补出省略的主语。

- 中文正文使用下表的名词。表名、函数、事件名、错误码、配置项用反引号，拼写与代码一致。
- 同一概念全文只用一个名词。服务器文档中的一次提问称为 Turn。写作客户端文档中同一次称为回合。同一篇不混用。
- 写机制、不变量、锁顺序，以及失败后留下的状态。数值和默认值从代码或配置读取，并标明出处。
- 决策段写已经选定的方案。现状段只写代码当前的行为。执行方案写阶段和验收。三类内容分节。
- 使用技术书面语。正文写出可核对的机制，不写宣传、项目介绍和口语填充。

口语填充包括「其实」「就是」「这块」「简单来说」「基本上」。判断要能回到代码、配置或决策原文。

「扫不到就先跳过」应写成「根源读取失败或清单无法解析时，本单位本轮零删除，并记下原因。」

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

`cancelled` 与 `failed` 是两种终态，正文分开写。Redis 可丢、可重复，文档不把它写成 claim 的依据。审批挂起后，同一 `run_id` 加 checkpoint 续跑；没有名为 ResumeTurn 的入口。

## 代码注释

新增或改动锁、事务边界、失败后的状态、回收放弃条件时，在同一处写注释。没有这些边界的函数不补注释。

- 注释使用中文，名词与上表一致。
- 只写不变量、锁顺序、哪一步失败会留下什么、为什么放弃整轮。代码已经表达的动作不注释。
- 注释不重述 ADR 段落，不写待办。

## 文档放哪

| 种类 | 位置 | 写什么 |
|---|---|---|
| 决策 | `docs/adr/NNN-*.md` | 状态行、决策、机制。现状段只写代码的真实行为 |
| 导览 | `docs/tour/pages/*.html` | 现行路径：入口、调用点、状态变化。人类入口 |
| 客户端与内核方案 | 壳与接头的方案文档 | 现行约定。改行为时改对应句子 |
| 执行方案 | `docs/` 下已有的执行方案 | 阶段和验收。不在 ADR 里再排一份阶段 |

ADR 开头是 `# ADR-NNN 标题` 和 `状态：提议。` 或 `状态：已实施。`。状态与代码不符时，改状态或改现状段。

导览页是 `<section class="page">`。步骤写调用点和状态。图上的句子不在正文再抄一遍。

## 流程图

`docs/assets/**/*.png` 的画法以 `.cursor/rules/docs-flow-diagram.mdc` 为准。样板以那份规则点名的图为准。本 skill 不重述那份规则。

正文图是按该规则重绘的控制流详图。Mermaid、Graphviz、等重卡片、Unicode `↓` 脊柱，以及在旧 PNG 上涂改的结果，不作为正文图。
