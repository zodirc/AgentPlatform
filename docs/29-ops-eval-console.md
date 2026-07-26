# Ops Eval Console（Web 评测台）

> **完整证明（默认）≡ CI**：与 GitHub Actions 同跑 `scripts/ci_proof.sh`（unit + `make gate`）。  
> **Golden 切片**：对已启动栈点选用例；切片绿 ≠ 合并证明。  
> 测试核心是结果一致，不是跟手时间。不进写作热路径（见 [13](13-rate-redlines.md) R1–R5）。  
> **边界**：Ops 是内部后端能力（密钥 URL + api）；与面向用户的 Web / `/workspace` / Work **文件系统隔离**。  
> **观测**：检索审计 → [§6](#6-检索审计观测-hm5--ro1)；模型信封 → [§7](#7-模型信封-hm4)；Raw → [§8](#8-raw-快照只读-hm2) · [33](33-harness-maturity-backlog.md)。  
> **速率纪律**：Ops 仅密钥 URL + 只读 API/页；**不**进入写作/Agent 工作台导航热路径，**不**改 `AgentEngine` / SSE 主路径（R1–R5）。

## 1. 入口

| 项 | 说明 |
|----|------|
| URL | `https://<host>/ops/<OPS_TEST_SECRET>/test` |
| 鉴权 | 路径密钥 ≡ API `Authorization: Bearer <OPS_TEST_SECRET>` |
| 关闭 | `.env` 中 `OPS_TEST_SECRET=` **空字符串**（键存在）→ 不挂载；**无此键**时 `make up` 等会自动生成 |

密钥勿提交仓库；错密钥不暴露「存在评测台」以外的信息（API 401/404）。

## 2. 产品行为

### 2.0 套件：`ci`（完整证明）vs `golden`（切片）

| 套件 | 作用 | 是否 ≡ CI |
|------|------|-----------|
| **`ci`（默认）** | 跑 `scripts/ci_proof.sh`：unit（ux / runtime / api / contracts）→ `make gate`（smoke + 全量 golden；**不**再跑一遍 runtime pytest） | **是** |
| **`golden`** | 进程内对当前 api/runtime 点选 Golden Turn | 否（可 skipped） |

`suite=ci` 通过 Docker socket 起 `agent-ops-proof` 镜像，把仓库以**宿主机同路径**挂进容器执行（与 compose 相对挂载兼容）。首次会构建镜像。`make gate` 会重建 runtime，结束后**恢复日常栈**（`GATE_SKIP_RESTORE=0`）。CI 无头用 `GATE_SKIP_RESTORE=1`。

### 2.1 Golden 切片行为

- **模式**：页面单选 `stub` / `live`（默认 stub）。
- **live 模型**：页面内评测专用 provider / base_url / model / api_key；**不**写入用户「设置 → 模型」。
- **用例**：扫描 `eval/golden/**/*.yaml`；可按 scenario / tag 过滤；每条 `pending → running → pass | fail | skipped`。
- **重启**：默认**不**重建容器。高级选项「跑前重建 runtime」在挂载 Docker socket + api 含 docker CLI 时可用。
- **工作区**：后端私有 scratch（默认 `/data/ops-eval/<run_id>/<case_id>/`，与用户 `/workspace` / Work 无关）；run 结束删除。
- **输出页** / **历史**：同完整证明。

### 2.2 结果态：`skipped` ≠ 失败（仅 golden）

**Skipped** 表示本台**故意不跑**该用例，不是断言失败。完整证明（`suite=ci`）**没有** skipped——失败即红。

进程内 Ops runner 无法驱动部分环境耦合命令时标 skipped（见下表）。这些由 **`suite=ci` / `make gate` / `make eval-*`** 覆盖。

| 命令 | 典型用例 | 为何 golden 不跑 |
|------|----------|------------------|
| `session-turns` | `shared.08`、`shared.11` | 需多 Turn / HA runner 编排 |
| `admin.create-provider` | `shared.10` | 需管理端写 provider 并激活 |
| `ws.stream` | `shared.14` | 需真实 WebSocket 客户端 |
| `wait-index` | `shared.16` | 需 outbox / 向量索引就绪探测 |

## 3. 技术要点

### 3.1 按 Turn 覆盖模型（golden；无需为 stub/live 重启）

`StartTurnCommand` 增加：

- `model_mode: stub | live | recorded | null`
- `model_override: { provider, model_name, api_key, base_url, … } | null`
- `ops_eval: bool` — **仅** api→runtime 且 `ops_eval=true` 时 runtime 接受覆盖；普通用户 Turn 忽略/拒绝。

Runtime 用 ContextVar（`turn_override`）绑定本 Turn 的 mode/override。审批恢复时 `TurnState.model_mode` 写入 checkpoint，避免 stub Turn resume 后误走 live。

### 3.2 完整证明（`suite=ci`）

| 项 | 落点 |
|----|------|
| 脚本 | `scripts/ci_proof.sh`（`PROOF_STEP=…` 可单步） |
| 镜像 | `deploy/ops-proof.Dockerfile` → `agent-ops-proof:local` |
| 编排 | `services/api/app/services/ops/proof.py` |
| api 挂载 | `..:/repo:ro` + docker.sock；宿主机路径由 inspect `/repo` 发现 |
| 与 CI | `.github/workflows/ci.yml` 同跑 `bash scripts/ci_proof.sh` |

### 3.3 API

前缀：`/api/v1/ops/eval`（需 `OPS_TEST_SECRET`）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/meta` | `restart_available`、`proof_available`、`ci_proof_cases` |
| GET | `/cases` | Golden 用例元数据 |
| GET | `/runs` | 历史列表（摘要，Postgres） |
| POST | `/runs` | `{ suite: golden\|ci, mode?, case_ids?, model?, restart_runtime? }` |
| GET | `/runs/{id}` | 状态与每条结果 |
| GET | `/runs/{id}/stream` | SSE 进度 |

## 4. 证明口径

**原则：结果一致优先于跟手时间。**

| 场景 | 路径 | 是否算证明 |
|------|------|------------|
| 合并前 / 本地「完整证明」/ CI | Ops **`suite=ci`** ≡ `make ci-proof` ≡ GitHub Actions | **是** |
| 改完立刻点选、看日志、调 live | Ops **`suite=golden`** | 否（切片） |
| 无头门禁半边 | `make gate` | 是（unit 以外的 docker 半边；全量仍用 `ci-proof`） |
| 专项 | `make eval-*` 等 | 专项 |

评测不挂写作工作台导航，避免误触。

## 5. 配置

```bash
# .env — 本地可留空；make up / start / up-web 会自动生成一次并打印 URL
OPS_TEST_SECRET=your-long-random-secret
# optional absolute host checkout path if inspect fails
# OPS_EVAL_REPO_HOST_PATH=/absolute/path/to/agent
# OPS_EVAL_WORKSPACE_ROOT=/data/ops-eval   # golden 私有 scratch（agent_data）；勿放用户 workspace
```

| 行为 | 说明 |
|------|------|
| 自动生成 | `.env` **没有** `OPS_TEST_SECRET` 键时，`make ensure-ops-secret`（以及 `up` / `start` / `up-web` / `up-api`）写入随机密钥并打印 URL |
| 不覆盖 | 已有非空值保持不变，URL 稳定 |
| 关闭评测台 | 设 `OPS_TEST_SECRET=`（空字符串，键仍在）并 `make up-api`；ensure **不会**再回填 |

Compose 为 api 挂载 **`agent_data`（`/data`，含 ops scratch）**、workspace（仅用户侧）、`eval/golden`、**仓库 `/repo`**、Docker socket；api 镜像需含 `docker` CLI。「跑前重建 runtime」与 `suite=ci` 均依赖 socket。

改完 api 后请 `make up-api`（需重建以挂上 `/data` + `/repo`）；web 改完 `make up-web`。

---

## 6. 检索审计观测（HM5 / RO1）

> **状态**：✅ 已落地（2026-07-24）— 事件 `audit` 三层 + Ops API/页；细项持续加厚见 [33](33-harness-maturity-backlog.md) HM5。  
> **定位**：Ops **观测**能力，与 §2 的 ci/golden **评测**并列；不是替代 `make gate`。

### 6.1 要解决什么

前台 Web Agent / Writing 用户发起的真实 Turn 里，`search_sources` 等检索发生后，研发/Ops 需要回答坏例三问（召回池 / 排序 / 进窗），而不能依赖用户侧栏截图。

### 6.2 谁用、看谁

| | |
|--|--|
| **使用者** | 持有 `OPS_TEST_SECRET` 的内部人员（后端观测台） |
| **被查看对象** | 前台 Web 用户的 Session / Turn（agent 或 writing scenario） |
| **不是** | 把三层审计默认展示给终端用户；不是改用户 workspace；不是 golden scratch 里的假用户 |

### 6.3 已落地能力

| 能力 | 说明 |
|------|------|
| 入口 | `/ops/<secret>/retrieval`（Ops 壳导航「检索审计」） |
| 浏览 | 默认列出**最近有检索的真实用户 Turn**（query / 命中数 / 时间）；点开看三层 |
| 精确跳转 | 可选折叠输入 `turn_id`（调试用） |
| 展示 | L1 `recall_pool` · L2 `ranked` · L3 `entered_context`（含 truncated） |
| 导出 | 页内「导出当前 JSON」 |
| API | `GET /api/v1/ops/retrieval/recent` · `GET /api/v1/ops/retrieval/turns/{turn_id}`（Bearer = `OPS_TEST_SECRET`）；只读 |
| 事件 | `retrieval.completed.payload.audit`（契约已扩）；**不**写入模型 tool_result |
| 鉴权 / 隔离 | 与 §1 同密钥；只读 DB；禁止写 `/workspace` |
| 读法 | L1 常宽于 L3；`rank_method` 应为 `lexical`/`none`/`cross_encoder`。若见 `rank_method=hybrid` 且三层同构，曾是 two-level 未传播 ContextVar 的捕获兜底（已修，见 [33](33-harness-maturity-backlog.md) HM5） |

### 6.4 与评测台的关系

```text
/ops/<secret>/test        → ci-proof / golden（人造用例、私有 scratch）
/ops/<secret>/retrieval   → 真实前台用户 Turn 的检索可观测（只读）
```

两者共享密钥与「内部后端」边界；数据面分离（评测 scratch ≠ 用户 Work）。

### 6.5 明确不做

- 在用户工作台导航挂「完整召回池」当默认产品功能  
- Ops 代用户重跑检索并写回其语料库  
- 无密钥的公开 debug 页  

## 7. 模型信封（HM4）

> **状态**：✅ 已落地 — 哈希必写 · **默认落全文**（`MODEL_ENVELOPE_SAMPLE_RATE` 默认 `1.0`）；高 fill / `MODEL_ENVELOPE_DEBUG` 仍强制全文。详见 [33](33-harness-maturity-backlog.md) HM4。

| 能力 | 说明 |
|------|------|
| 入口 | `/ops/<secret>/envelopes`（Ops 壳导航「模型信封」） |
| 浏览 | 默认列出最近有信封落盘的 Turn；点开看哈希 / 全文 |
| API | `GET /api/v1/ops/envelopes/recent` · `GET /api/v1/ops/envelopes/turns/{turn_id}` |
| 表 | `model_request_envelopes`（Alembic `0015`） |
| 写入 | assemble 后异步；不进 SSE / 默认投影 |
| 降采样 | 若需省盘：设 `MODEL_ENVELOPE_SAMPLE_RATE=0.05` 等后重建 runtime |

与 §6 同密钥、只读；回答「那一步模型看见了什么」。

## 8. Raw 快照只读（HM2）

| 能力 | 说明 |
|------|------|
| 入口 | `/ops/<secret>/raw`（Ops 壳「Raw 快照」） |
| 浏览 | 最近有 raw 的 Turn；点开看 step 快照；messages 默认折叠 |
| API | `GET /api/v1/ops/raw/recent` · `GET /api/v1/ops/raw/turns/{turn_id}` |
| 表 | `session_raw_snapshots`（Alembic `0014`） |
| 纪律 | **永不**把该仓内容直接当作模型窗 |
| 同 Turn 互链 | 检索 / 信封 / Raw 页顶「同 Turn 观测」+ `?turn=` |

## 9. 观测页加厚（旁路 UX · 2026-07）

| 项 | 说明 |
|----|------|
| 诊断条 | 检索页对「无 audit / hybrid 三层同构 / L3 全截断 / 层差」给出提示（纯前端，不调 runtime） |
| 层差高亮 | L1∖L2、L2∖L3 的 chunk 标记 `only-here` |
| 边界 | 仍不向用户工作台挂完整召回池；评测 scratch ≠ 用户 Work |
