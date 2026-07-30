# 38 — 镜像分层重建方案（deps / app）

> **状态**：BR1–BR5 ✅ 已落地（2026-07-30）· BR6 ⏸ 可选  
> **触发**：改少量业务代码后 `make up-runtime` / `up-api` 仍常付「整镜像 + pip（+ ST 烘焙）」成本；允许重建、不追求热重载，但要**缩小重建范围**。  
> **关联**：[03](../core/03-docker-runtime.md) · [ADR-001](../core/02-architecture.md) · [ADR-003](../core/03-docker-runtime.md) · [13](../core/13-rate-redlines.md) · [28](../topics/proof-gate-and-ux-signals.md) · CI `runtime-lite`  
> **硬约束**：
>
> 1. **不影响** Agent 交互逻辑与交互思路（loop / 工具 / Profile / SSE / 审批 / 检索语义不变）  
> 2. 思路成熟：业界常规的 **依赖层与应用层分离** + BuildKit 缓存，**不**为加速再拆业务微服务  
> 3. 对外仍是 **api / runtime / web** 三服务（ADR-001）；Scenario 差异继续只在 Profile
>
> **落地摘要**：各服务 Dockerfile 多阶段 `deps` → `app`（stub 装 pip）；compose `target: app`；`API_REBUILD_DEPS` / `RUNTIME_REBUILD_DEPS` / `WEB_REBUILD_DEPS=1` 才 `--no-cache`。
---

## 0. 一句话

**服务边界不变；把「少变的依赖/模型」锁进 deps 镜像，「常改的源码」只打薄 app 层。改代码付薄层重建，改依赖才付重层。**

---

## 1. 问题陈述

| 现象 | 真实原因 | 误判 |
|------|----------|------|
| 改一行 `tools.py` / `system.md` 也慢 | Dockerfile 在 `pip install` **之前** `COPY` 整个 `app/` → 源码变更打穿依赖层 | 「模块太大，要拆服务」 |
| `up-runtime` 远慢于 `up-web` | 默认 `Dockerfile.retrieval` 含 torch + ST + 模型烘焙 | 「Python 天生慢」 |
| 已有 `up-api` / `up-runtime` / `up-web` 仍不够 | 服务级分离有了，**镜像内层**未分离 | 「再拆 intel/retrieval 容器」 |

**产品约束（用户已确认）**：

- 重建**可允许**；热重载（`make dev`）**非本方案主路径**（可保留作可选加速，不作为验收依赖）  
- 目标是缩短 **改代码 → 镜像可用** 的墙钟时间  
- 交互逻辑 / 思路零改动

---

## 2. 非目标（明确否决）

| 否决 | 理由 |
|------|------|
| 按 Scenario / RAG / intel 再拆可独立部署的执行服务 | 动拓扑与契约；与「一个 Runtime」冲突；对「改 20 行工具」帮助有限 |
| 把热重载挂载当作默认生产路径 | 与「允许重建、成熟发布镜像」不一致；验收仍以镜像为准 |
| 为加速合并 api+runtime 回单体 | 违背 ADR-001 |
| 在 Turn 热路径加「构建/缓存」逻辑 | 违 [13](../core/13-rate-redlines.md)；构建属运维面 |
| CI proof 默认打满 ST 烘焙镜像 | 已有 `runtime-lite`；分层后 CI 仍走 lite |

---

## 3. 目标架构

### 3.1 逻辑图

```text
                    ┌─────────────────────────┐
  少变              │  *:deps 镜像              │
  pyproject/lock    │  apt + pip/pnpm         │
  ST/模型烘焙       │  (+ runtime retrieval)  │
                    └───────────┬─────────────┘
                                │ FROM
                    ┌───────────▼─────────────┐
  常变              │  最终服务 tag（薄 app）   │
  app/**            │  COPY 源码 / vite dist   │
  scenarios/**      │  秒～几十秒级（缓存命中时） │
                    └─────────────────────────┘
```

| 镜像角色 | 示例 tag | 何时重建 |
|----------|----------|----------|
| runtime-deps | `agent-platform-runtime:deps` | `pyproject` / Dockerfile.deps / 嵌入模型版本变 |
| runtime（最终） | `agent-platform-runtime:default` | 业务代码变；**FROM deps** |
| runtime-lite | `agent-platform-runtime:lite` | CI/eval；可同样 deps/app，或保持单文件但修好 COPY 顺序 |
| api-deps / api | 同上模式 | 同上 |
| web | 已多阶段；保证 `pnpm install` 不被 `src` 打穿 | lock 变才重装 |

### 3.2 与现网 compose 的关系

- `deploy/docker-compose.yml` **服务名、端口、环境变量、卷、健康检查不变**  
- 仅 `build.dockerfile` / `target` / 额外 `image` tag 指向分层产物  
- 运行时进程、内部 URL、`INTERNAL_SERVICE_TOKEN`、事件协议：**不变**

### 3.3 当前反模式（必须修）

以 runtime / api 为例（现状）：

```dockerfile
COPY pyproject.toml …
COPY app /tmp/…/app          # ← 源码进入依赖层输入
RUN pip install /tmp/…         # ← 任意 .py 变更 → 重装全部依赖
COPY app /app/app
```

**目标形态**：

```dockerfile
# Dockerfile.deps（或 stage deps）
COPY pyproject.toml …          # 仅清单（必要时 + poetry.lock/uv.lock）
RUN pip install …              # 不 COPY 业务源码；可用空包/最小 stub 满足 packaging

# Dockerfile / stage app
FROM …:deps
COPY app /app/app
COPY scenarios …               # 或已含在 app 树内
```

> 若 packaging 要求包内有模块才能 `pip install`：用 **最小 stub 包**（`app/__init__.py` + pyproject）装依赖，正式源码仍在最终 `COPY`；或改为「deps 只装 requirements 导出、app 层 editable」——实施时择一，以「源码变更不触发 pip」为准。

---

## 4. 分批落地（BR）

| 批 | 内容 | 风险 | 验收 |
|----|------|------|------|
| **BR0** | 本文定稿；索引挂到 [README](README.md) / [03](../core/03-docker-runtime.md) 指针 | 无 | 评审通过 |
| **BR1** | **api**：deps/app 分层或等价「先清单后源码」；修 COPY 顺序 | 低 | 只改 `services/api/app/**` 时 BuildKit 显示 pip 层 CACHE；`make up-api` 明显缩短 |
| **BR2** | **runtime-lite** 同样修 COPY 顺序（CI/gate 主路径） | 低 | `make gate` / `ci_proof` 绿；lite 构建在仅改 app 时命中 pip 缓存 |
| **BR3** | **runtime retrieval**：`Dockerfile.deps`（含 ST 烘焙）+ 薄 app `FROM deps`；compose 默认最终 tag | 中 | 只改 `system.md`/工具时不重下模型；`make up-runtime` 薄层；检索 smoke 仍 ST |
| **BR4** | Makefile 旋钮：`*_REBUILD_DEPS=1` 才强制无缓存打 deps；文档化日常 vs 依赖变更 | 低 | `make help` 有说明；默认路径不 `--no-cache` |
| **BR5** | web：复核 install/`COPY src` 顺序；可选 `web:deps`（通常收益小于 api/runtime） | 低 | 只改 `src` 时 pnpm 层 CACHE |
| **BR6** | （可选）CI/本地 BuildKit `cache-from`/`cache-to` 或 registry 中的 `:deps` 预热 | 中 | 冷机第二次构建 deps 可复用 |

**推荐实施序**：BR1 → BR2 → BR3 → BR4 →（BR5/BR6 按需）。

---

## 5. 开发者工作流（方案落地后）

| 场景 | 命令 | 预期 |
|------|------|------|
| 日常改 api/runtime/web **业务代码** | `make up-api` / `up-runtime` / `up-web`（已加 `--no-deps`，互不连带重建） | 薄层重建 + 该容器 recreate |
| 改 `pyproject.toml` / 加系统包 / 换嵌入模型 | `API_REBUILD_DEPS=1 make up-api` 等 | 允许打 deps（慢可接受） |
| 全栈演示机首装 / Dockerfile.deps 大变 | `make up` 或对应 `*_REBUILD_DEPS=1` | 一次性付 deps；之后日常走单服务 up-* |
| CI / Golden | 现有 lite + `ci_proof` | **不**因本方案改交互断言 |

可选保留：`make dev` 热挂载——**非本方案验收项**。

---

## 6. 对交互与证明的影响面（必须为零）

| 面 | 是否允许变 |
|----|------------|
| AgentEngine / ToolExecutor / ScenarioProfile 语义 | ❌ |
| SSE 事件、审批、Cancel | ❌ |
| 检索算法、IX3 `effect_ready` 口径 | ❌ |
| 工具名与白名单 | ❌ |
| Dockerfile / compose build / Makefile / CI cache | ✅ |
| 镜像体积与构建时间 | ✅（应变好） |

**回归**：`make gate`（或至少 `smoke` + 相关 unit）在 BR1–BR3 合并前绿。

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| packaging 无法「无源码 pip install」 | stub 包或 requirements 导出（§3.3） |
| deps 与 app Python 路径不一致 | 单一 `WORKDIR`/`PYTHONPATH` 约定；smoke 探活 |
| 开发者误以为「永远不用重建 deps」 | Makefile 检测 `pyproject` 变更时可提示；文档写清 |
| `:deps` 标签漂移导致「薄层很快但行为旧」 | app 层 `FROM` 钉 digest 或同 compose build 一次产出两 tag |
| 本地磁盘镜像变多 | 现有 `DOCKER_AUTO_PRUNE`；deps 少变 |

---

## 8. 成功度量（建议）

在**同一机器、温缓存**下对比（记录到 PR 描述即可）：

| 操作 | 现状（约） | 目标 |
|------|------------|------|
| 只改 `services/runtime/app/tools/…` → `make up-runtime` | 常触发 pip ± ST | **不**触发 pip/模型层；以 BuildKit CACHE 为准 |
| 只改 `services/api/app/…` → `make up-api` | 常触发全量 pip | pip 层 CACHE |
| 只改嵌入模型名 / pyproject | 全量慢 | 允许慢；明确走 `*_REBUILD_DEPS` |

不设虚假绝对秒数（机器与镜像源差异大）；以 **层缓存是否命中** 为客观门闩。

---

## 9. 文档与代码落点（实施时）

| 项 | 路径 |
|----|------|
| 本方案 | `docs/38-image-layer-rebuild-plan.md` |
| 部署真源更新 | `docs/03-docker-runtime.md` §5 Dockerfile 规范（增加 deps/app） |
| api | `services/api/Dockerfile`（+ 可选 `Dockerfile.deps`） |
| runtime | `services/runtime/Dockerfile` · `Dockerfile.retrieval`（拆 deps）· lite 同步 |
| web | `services/web/Dockerfile`（复核） |
| compose | `deploy/docker-compose.yml` build args/target |
| 入口 | `Makefile` `up-*` + `*_REBUILD_DEPS` |

可选后续 ADR：若 deps 镜像成为对外约定，可补 **ADR-020（镜像分层）**；本阶段用本文 + 03 修订即可，避免 ADR 通胀。

---

## 10. 决策摘要

| 问题 | 决策 |
|------|------|
| 如何缩短改代码重建？ | **deps / app 分层** + 修正 COPY 顺序 |
| 是否拆业务服务？ | **否** |
| 是否依赖热重载？ | **否**（可选，非主路径） |
| 是否影响 Agent 交互？ | **否**（硬约束） |
| CI？ | 继续 **lite**；分层收益留给日常 ST 镜像 |

---

## 11. 状态跟踪

| ID | 项 | 状态 |
|----|----|------|
| BR0 | 方案文档 | ✅ 本文 |
| BR1 | api 分层 / COPY 序 | ✅ `services/api/Dockerfile` `deps`→`app` |
| BR2 | runtime-lite COPY 序 | ✅ `services/runtime/Dockerfile` |
| BR3 | retrieval deps+app | ✅ `Dockerfile.retrieval` + compose `target: app` |
| BR4 | Makefile 旋钮与帮助 | ✅ `*_REBUILD_DEPS=1` → `--no-cache` |
| BR5 | web 复核 | ✅ install 仍在 src 之前（注释对齐） |
| BR6 | 远程/持久 BuildKit cache | ⏸ 可选 |
