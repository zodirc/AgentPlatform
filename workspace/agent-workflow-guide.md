# Agent 工作流流程文档

> 本文档描述当前项目的 Agent 平台整体架构、工作流与操作流程。
> 项目基于 **「一个内核，多个场景」** 的设计理念。

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [场景与路由](#3-场景与路由)
4. [Agent 工作流生命周期](#4-agent-工作流生命周期)
5. [工具系统与审批机制](#5-工具系统与审批机制)
6. [文件组织与工作区](#6-文件组织与工作区)
7. [写作场景专项流程](#7-写作场景专项流程)
8. [模型配置](#8-模型配置)
9. [启动与运维](#9-启动与运维)
10. [常见故障排查](#10-常见故障排查)

---

## 1. 项目概述

本项目是一个 **AI Agent 运行时平台**，提供统一的 Agent 内核与多个专用场景。

| 特性 | 说明 |
|------|------|
| **内核统一** | 所有场景共享同一套 Agentic Loop 运行时 |
| **场景分离** | 通过不同路由（`/writing`、`/agent`、`/interview`）提供差异化能力 |
| **工具驱动** | Agent 通过工具（读文件、写文件、搜索、委派等）与外界交互 |
| **人工审批** | 敏感操作需要人工批准，确保安全可控 |
| **沙箱隔离** | 工作区与项目源码隔离，避免误操作 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────┐
│              Web 工作台 (React)           │
│   /writing    /agent    /interview       │
└────────────────┬────────────────────────┘
                 │ SSE / HTTP
┌────────────────▼────────────────────────┐
│           API 层 (控制面 + SSE)           │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Runtime (Agentic Loop)           │
│   ┌──────────────────────────────────┐  │
│   │   Agent 内核 (LLM + Tool Exec)    │  │
│   │   ├─ 思考 → 调用工具 → 观察结果    │  │
│   │   ├─ 循环直至完成或需要审批         │  │
│   │   └─ 支持子 Agent 委派            │  │
│   └──────────────────────────────────┘  │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│            PostgreSQL (持久化)           │
└─────────────────────────────────────────┘
```

### 2.2 Agentic Loop 核心流程

```
 ┌──────────┐
 │ 用户输入  │
 └────┬─────┘
      ▼
 ┌──────────────┐
 │  任务解析     │ ← LLM 理解用户意图
 └──────┬───────┘
        ▼
 ┌──────────────┐
 │  规划步骤     │ ← 拆解为子任务
 └──────┬───────┘
        ▼
    ┌─────┴─────┐
    │           │
    ▼           ▼
 ┌──────┐  ┌──────┐
 │思考   │  │调用工具│
 └──┬───┘  └──┬───┘
    │         │
    └──┬──────┘
       ▼
 ┌──────────────┐
 │  观察结果     │
 └──────┬───────┘
        ▼
    ┌─────┴─────┐
    │ 需要审批？  │──── 是 ──→ ┌──────────────┐
    └─────┬─────┘            │ waiting_approval │
          │ 否               │ 等待用户批准/拒绝 │
          ▼                  └────────────────┘
    ┌──────────────┐               │ 批准
    │ 是否完成？    │◄──────────────┘
    └──┬───┬───────┘
  是/否│   │
       ▼   │(继续循环)
 ┌─────────┘
 ▼
┌────────────────┐
│ status=completed│
└────────────────┘
```

---

## 3. 场景与路由

项目提供三个主要场景，通过不同 URL 路由访问：

| 场景 | 路由 | 用途 | 特色工具 |
|------|------|------|---------|
| **写作 (Writing)** | `/writing` | 大纲、章节撰写、引用管理、Patch 审阅 | `draft_section`, `propose_patch`, `search_sources` |
| **通用 Agent** | `/agent` | 文件浏览、搜索、编辑、子任务委派 | `list_dir`, `read_file`, `write_file`, `delegate`, `search_sources` |
| **访谈 (Interview)** | `/interview` | 访谈场景（当前为 stub） | — |

### 3.1 写作场景 (Writing)

写作场景专注于文档创作工作流：

```
用户需求
   │
   ▼
┌───────────────┐
│ 制定大纲       │ → outline.md
└───────┬───────┘
        ▼
┌───────────────┐
│ 撰写章节       │ → sections/*.md
│ (draft_section)│
└───────┬───────┘
        ▼
┌───────────────┐
│ 引用管理       │ → sources/*.md
│ (search_sources)│
└───────┬───────┘
        ▼
┌───────────────┐
│ 审查与修改     │ → propose_patch
│ (patch 审阅)   │
└───────┬───────┘
        ▼
┌───────────────┐
│ 导出文档       │ → exports/document.md
└───────────────┘
```

### 3.2 通用 Agent 场景 (Agent)

通用 Agent 提供全面的文件系统操作能力：

- 列出目录结构 (`list_dir`)
- 读取文件内容 (`read_file`)
- 写入/创建文件 (`write_file` — 需审批)
- 搜索代码库 (`search_codebase`)
- 搜索源材料 (`search_sources`)
- 子任务委派 (`delegate`)
- 运行命令 (`run_command` — 需审批)
- 运行测试 (`run_tests`)

---

## 4. Agent 工作流生命周期

每一轮 Agent 交互都遵循以下生命周期：

### 4.1 状态流转图

```
                 ┌──────────┐
                 │  idle     │ ← 初始状态，等待用户输入
                 └────┬─────┘
                      │ 用户发送任务
                      ▼
                 ┌──────────┐
                 │  running  │ ← Agent 开始执行
                 └────┬─────┘
                      │
            ┌─────────┼─────────┐
            ▼         ▼         ▼
      ┌─────────┐┌─────────┐┌─────────┐
      │思考/工具 ││ 等待审批 ││ 委派子Agent│
      │ (循环)   ││waiting_ ││delegate  │
      │         ││approval ││         │
      └────┬────┘└────┬────┘└────┬────┘
           │          │           │
           └──────────┼───────────┘
                      │
                      ▼
                 ┌──────────┐
                 │ completed │ ← 本轮结束
                 └──────────┘
```

### 4.2 详细步骤说明

#### 步骤 1：用户输入

用户在 Web 工作台底部输入框中用自然语言描述任务。

**示例：**
- 「列出 workspace 目录结构」
- 「读取 README.md 并总结」
- 「创建一份项目说明文档」（会触发 `write_file`，需审批）

#### 步骤 2：任务解析与规划

Agent 内核（LLM）理解用户意图，拆解为可执行的工具调用序列。

#### 步骤 3：工具执行循环

Agent 根据需要反复执行以下循环：
1. **思考** — 确定下一步需要做什么
2. **调用工具** — 执行具体操作（读文件、搜索等）
3. **观察结果** — 分析工具返回的信息
4. **判断** — 是否继续、是否完成、是否需要审批

#### 步骤 4：审批节点

当 Agent 调用敏感工具（如 `write_file`、`run_command`）时，状态变为 `waiting_approval`：

- 用户在界面中点 **「批准」** 继续执行
- 或点 **「拒绝」** 中止该操作

#### 步骤 5：完成

当 `status=completed` 时表示本轮 Agent 交互结束。用户可继续发起新一轮任务。

---

## 5. 工具系统与审批机制

### 5.1 工具清单

| 工具名称 | 用途 | 是否需要审批 | 可用场景 |
|---------|------|------------|---------|
| `list_dir` | 列出目录内容 | ❌ 否 | agent, writing |
| `read_file` | 读取文件 | ❌ 否 | agent, writing |
| `write_file` | 创建/覆盖文件 | ✅ 是（默认） | agent, writing |
| `edit_file` | 编辑已有文件（替换文本） | ✅ 是 | agent, writing |
| `propose_patch` | 提出补丁供审阅 | ❌ 否 | writing |
| `search_codebase` | 搜索代码库 | ❌ 否 | agent |
| `search_sources` | 搜索源材料 | ❌ 否 | agent, writing |
| `delegate` | 委派子 Agent 任务 | ❌ 否 | agent, writing |
| `run_command` | 执行 Shell 命令 | ✅ 是 | agent |
| `run_tests` | 运行测试 | ❌ 否 | agent |
| `draft_section` | 撰写章节草稿 | ❌ 否 | writing |
| `grep` | 搜索文件内容 | ❌ 否 | agent, writing |
| `glob` | 按模式查找文件 | ❌ 否 | agent, writing |

### 5.2 审批机制说明

- **敏感操作**：`write_file`、`edit_file`、`run_command` 等修改系统的操作默认需要人工审批
- **安全读取**：`read_file`、`list_dir`、`search_codebase` 等只读操作无需审批
- **审批界面**：在 Web 工作台中，当状态变为 `waiting_approval` 时，会显示待审批的工具调用详情
- **审批决策**：用户可批准（允许执行）或拒绝（取消操作）

---

## 6. 文件组织与工作区

### 6.1 工作区结构

当前工作区（`/workspace`）的文件组织如下：

```
workspace/
├── README.md              # 项目简介
├── AGENT.md               # Agent 平台使用说明（中文）
├── outline.md              # 文档大纲
├── notes.md                # 通用笔记
├── large_file.md           # 大文件（测试用）
├── agent-workflow-guide.md # 本流程文档
├── app/
│   └── engine.py           # AgentEngine 核心类
├── sections/
│   ├── 01.md               # 章节 1
│   ├── 02.md               # 章节 2
│   ├── a.md                # 章节 A
│   └── notes.md            # 章节笔记
├── sources/
│   ├── ref-a.md            # 参考资料 A
│   └── new-chunk.md        # 新增材料
├── exports/
│   └── document.md         # 导出文档（合并所有章节）
└── .agent/
    └── revisions/
        ├── 02.md            # 02 章节的修订稿
        └── notes.md         # 修订笔记
```

### 6.2 文件用途说明

| 目录/文件 | 用途 |
|-----------|------|
| `sections/` | 存放文档的各个章节，每个 `.md` 文件代表一个章节 |
| `sources/` | 存放引用材料、参考文献、采访记录等源数据 |
| `exports/` | 存放最终导出的合并文档 |
| `.agent/revisions/` | 存放 Agent 生成的修订稿/草稿 |

### 6.3 沙箱隔离

- 容器内路径：`/workspace`
- 宿主机映射：`workspace/` 目录（由 `.env` 中 `WORKSPACE_HOST_PATH` 配置）
- Agent 的所有文件操作**均在沙箱内**，与项目源码隔离

---

## 7. 写作场景专项流程

写作场景是一个完整的文档创作流水线，以下是典型的工作流：

### 7.1 写作流水线

```
Phase 1: 制定大纲
├── 用户提出写作主题
├── Agent 生成 outline.md
└── 用户审阅并确认大纲

Phase 2: 撰写章节
├── Agent 使用 draft_section 逐章撰写
├── 每章写入 sections/*.md
└── 可从 sources/*.md 引用材料

Phase 3: 引用管理
├── 使用 search_sources 搜索参考资料
├── 在 sources/ 中查找或创建引用材料
└── 🤖 cite:xxx 格式标记引用

Phase 4: 审查与修改
├── 用户审阅已有内容
├── Agent 使用 propose_patch 提出修改方案
└── 💡 patch 审阅通过后生效

Phase 5: 合并导出
├── 读取所有 sections/*.md
├── 合并为 exports/document.md
└── 🎉 最终文档就绪
```

### 7.2 引用机制

在写作中可以使用 `cite:xxx` 格式的引用标记，指向 `sources/` 中的资料。例如：

- 参考材料 `sources/ref-a.md` 中定义 `cite:ref-a`
- 在章节正文中引用 `cite:ref-a` 来标注来源

### 7.3 版本修订

Agent 生成的修订稿存放在 `.agent/revisions/` 目录下，与正式章节区分：
- `sections/02.md` — 正式章节
- `.agent/revisions/02.md` — 修订版本

---

## 8. 模型配置

### 8.1 配置方式

通过 Web 设置页（`http://localhost/settings/model`）进行模型配置：

| 字段 | 说明 |
|------|------|
| `provider` | 模型提供商（如 `deepseek`） |
| `model_name` | 模型名称（如 `deepseek-chat`） |
| `base_url` | API 地址（官方可留空，中转填兼容地址） |
| `API Key` | 您的 API 密钥 |

### 8.2 环境变量

`.env` 文件中必须设置：

```env
MODEL_MODE=live           # live=调用真实模型, stub=返回固定文本
MODEL_TIMEOUT_SECONDS=120 # 模型超时时间
AUTH_ENABLED=true         # 是否启用管理员认证
ADMIN_PASSWORD=admin      # 管理员密码
WORKSPACE_HOST_PATH=./workspace  # 工作区宿主机路径
```

> **注意**：`MODEL_MODE=stub` 时 Agent 仅返回固定占位文本，不会调用真实模型。

---

## 9. 启动与运维

### 9.1 快速启动

```bash
# 1. 进入项目目录
cd /path/to/agent

# 2. 首次使用：复制环境变量配置
cp .env.example .env

# 3. 确保 MODEL_MODE=live 以调用真实模型
# 4. 启动服务
make up
```

### 9.2 访问地址

| 页面 | 地址 |
|------|------|
| 写作场景 | `http://localhost/writing` |
| Agent 场景 | `http://localhost/agent` |
| 模型设置 | `http://localhost/settings/model` |

### 9.3 管理员认证

当 `AUTH_ENABLED=true` 时，需要认证才能使用：

- 用户名：`admin`
- 密码：`.env` 中 `ADMIN_PASSWORD`（默认 `admin`）

---

## 10. 常见故障排查

| 现象 | 原因 | 解决方法 |
|------|------|---------|
| Agent 只返回固定文本 | `MODEL_MODE=stub` | 设置 `MODEL_MODE=live` |
| 工具调用卡住等待 | 状态为 `waiting_approval` | 在界面中点击「批准」或「拒绝」 |
| 模型无响应 | 超时时间不足 | 增大 `MODEL_TIMEOUT_SECONDS` |
| 认证失败 | 密码不正确 | 检查 `.env` 中 `ADMIN_PASSWORD` |
| 文件访问不到 | 路径超出工作区 | Agent 操作仅限于 `/workspace` 内 |
| 模型返回错误 | API Key 或地址错误 | 检查 Web 设置页的模型配置 |

---

## 附录 A：典型交互示例

### 示例 1：浏览项目结构

```
用户: "列出 workspace 目录结构"
Agent: → list_dir(".") → 输出目录树
```

### 示例 2：创建说明文档

```
用户: "创建一份 AGENT.md 说明文档"
Agent: → 思考并规划内容
       → write_file("AGENT.md", ...)  [需用户批准]
       → 用户点击「批准」
       → 文件写入成功
       → status=completed
```

### 示例 3：写作流程

```
用户: "帮我写一篇关于 Agent 工作流的文章"
Agent: → 制定大纲 → outline.md
       → 撰写章节 → sections/01.md
       → 补充引用 → sources/ref-a.md
       → 审查修改 → propose_patch
       → 合并导出 → exports/document.md
```

---

> **文档版本**：v1.0  
> **最后更新**：2025 年  
> **适用范围**：当前 Agent 平台（非旧版 agent-langraph）
