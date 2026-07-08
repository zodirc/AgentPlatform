# Agent Platform 使用说明

> 本文档描述当前运行在 `http://localhost` 的 **Agent Platform**（非旧版 agent-langraph）。

## 1. 这是什么

一个「**一个内核，多个场景**」的 Agent 运行时：

| 场景 | 路由 | 用途 |
|------|------|------|
| **writing** | `/writing` | 写作：大纲、章节、引用、patch 审阅 |
| **agent** | `/agent` | 通用 Agent：读文件、列目录、写文件、检索、子任务委派 |
| **interview** | `/interview` | 访谈（stub） |

底层架构：`api`（控制面 + SSE） + `runtime`（Agentic Loop） + `web`（React 工作台） + `postgres`。

## 2. 如何启动

```bash
cd /path/to/agent
cp .env.example .env   # 首次
# 必须设置 MODEL_MODE=live 才会调用真实模型（stub 只回固定占位文本）
make up
```

浏览器打开：**http://localhost/writing** 或 **http://localhost/agent**

管理员认证（`AUTH_ENABLED=true` 时）：

- 用户名：`admin`
- 密码：`.env` 中 `ADMIN_PASSWORD`（默认 `admin`）

模型配置：**http://localhost/settings/model**（保存后下一 Turn 热生效）

## 3. 模型配置（DeepSeek 示例）

Web 设置页填写：

| 字段 | 值 |
|------|-----|
| provider | `deepseek` |
| model_name | `deepseek-chat` 或你的中转模型名 |
| base_url | 官方可留空；中转填兼容地址 |
| API Key | 你的 DeepSeek Key |

`.env` 中还需：

```env
MODEL_MODE=live
MODEL_TIMEOUT_SECONDS=120
```

## 4. 日常使用流程

1. 打开对应场景工作台（如 `/agent`）
2. 在底部输入框发送任务（自然语言即可）
3. 观察右侧/下方 **事件流**、**工具时间线**、**输出**
4. 若状态变为 `waiting_approval`：说明有敏感工具（如 `write_file`）待批准 → 点击 **批准** 继续
5. `status=completed` 表示本轮结束

### 示例任务

- 「列出 workspace 目录结构」
- 「读取 README.md 并总结」
- 「创建一份 AGENT.md 说明文档」（会触发 `write_file`，需批准）

## 5. 工具与审批

**agent** 场景常用工具：

- `list_dir` — 列目录
- `read_file` — 读文件
- `write_file` — 写文件（**默认需人工批准**）
- `search_sources` — 检索
- `delegate` — 委派子 Agent

写作场景另有 `draft_section`、`propose_patch` 等。

## 6. 工作区（沙箱）

容器内路径：`/workspace`  
宿主机映射：`workspace/` 目录（`.env` 中 `WORKSPACE_HOST_PATH`）

Agent 读写文件均在此目录内，与项目源码隔离。

## 7. 故障排查

| 现象 | 原因 | 处理 |
|------|------|------|
| `[stub] Acknowledged: ...` | `MODEL_MODE=stub` | `.env` 设 `MODEL_MODE=live` 并重建 runtime |
| `status=failed` + model 400 | 工具消息序列损坏 | 已修复；重建 runtime |
| `model_timeout` | 超时过短 | `.env` 设 `MODEL_TIMEOUT_SECONDS=120` |
| `waiting_approval` 不动 | 等待批准写文件 | 工作台点击批准 |
| 身份验证弹窗 | `AUTH_ENABLED=true` | admin / 你的 ADMIN_PASSWORD |

查看日志：

```bash
make logs
# 或
docker logs agent-runtime --tail 100
```

## 8. 与旧 agent-langraph 区别

| 项目 | 端口 | 说明 |
|------|------|------|
| **本 Agent** | **80** | 新架构，容器名 `agent-*` |
| agent-langraph | 8080/8081 | 旧项目，勿混淆 |

---

*由 Agent Platform 生成 · 场景：agent · 工作区：/workspace*
