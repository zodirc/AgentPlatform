# Ops Eval Console（Web 评测台）

> 日常自测主路径：对**已启动**的 api/runtime 跑 Golden Turn，可视化红绿。  
> 不进写作热路径（见 [13](13-rate-redlines.md) R1–R5）。用例契约仍以 [11](11-eval-and-golden-turns.md) 为准。

## 1. 入口

| 项 | 说明 |
|----|------|
| URL | `https://<host>/ops/<OPS_TEST_SECRET>/test` |
| 鉴权 | 路径密钥 ≡ API `Authorization: Bearer <OPS_TEST_SECRET>` |
| 关闭 | `.env` 中 `OPS_TEST_SECRET` **为空** → 不挂载 `/api/v1/ops/eval/*`；错密钥对 Web 显示「无效密钥」 |

密钥勿提交仓库；错密钥不暴露「存在评测台」以外的信息（API 401/404）。

## 2. 产品行为

- **模式**：页面单选 `stub` / `live`（默认 stub）。
- **live 模型**：页面内评测专用 provider / base_url / model / api_key；**不**写入用户「设置 → 模型」。
- **用例**：扫描 `eval/golden/**/*.yaml`；可按 scenario / tag 过滤；每条 `pending → running → pass | fail | skipped`。
- **重启**：默认**不**重建容器。高级选项「跑前重建 runtime」在挂载 Docker socket + api 含 docker CLI 时可用。
- **工作区**：每次 run 使用 `/workspace/.ops-eval/<run_id>/<case_id>/` 临时子目录（api 常以 root 写目录，runtime 为 uid 1000；runner 会把 ops 树 chmod 为可写）。
- **输出页**：`/ops/<SECRET>/test/runs/<run_id>` — 独立日志页，含每条用例 pass/fail/skipped、步骤与事件序列。
- **主题**：与主 Web 相同（墨色 / 纸色 / 高对比），页眉切换。

### 2.1 结果态：`skipped` ≠ 失败

**Skipped** 表示本台**故意不跑**该用例，不是断言失败。

进程内 Ops runner 无法驱动部分环境耦合命令。用例 `commands` 含下列类型时，状态为 `skipped`，`skip_reason` 形如 `unsupported ops commands: [...]`：

| 命令 | 典型用例 | 为何 Ops 不跑 |
|------|----------|----------------|
| `session-turns` | `shared.08`、`shared.11` | 需多 Turn / HA runner 编排 |
| `admin.create-provider` | `shared.10` | 需管理端写 provider 并激活 |
| `ws.stream` | `shared.14` | 需真实 WebSocket 客户端 |
| `wait-index` | `shared.16` | 需 outbox / 向量索引就绪探测 |

这些仍由 **`make gate` / `make eval-*`**（隔离栈）覆盖，见 [28](28-proof-gate-and-ux-signals.md)。

默认「全选」会**预先排除**含上述命令的用例，以及 `ha` / `queue` / `stall` tag、`model_mode: recorded`、stub 模式下的 `live` tag。若手动勾选含不支持命令的用例，则会进入 run 并以 **skipped** 收尾（总计里会计入，但不计 fail）。

## 3. 技术要点

### 3.1 按 Turn 覆盖模型（无需为 stub/live 重启）

`StartTurnCommand` 增加：

- `model_mode: stub | live | recorded | null`
- `model_override: { provider, model_name, api_key, base_url, … } | null`
- `ops_eval: bool` — **仅** api→runtime 且 `ops_eval=true` 时 runtime 接受覆盖；普通用户 Turn 忽略/拒绝。

Runtime 用 ContextVar（`turn_override`）绑定本 Turn 的 mode/override，`create_gateway` / `resolve_model_config` 读取之。

**审批恢复**：`approve` / `deny` 可能从 checkpoint 重建 `PendingTurn`。`TurnState.model_mode` 会写入 checkpoint；重建 gateway 前重新 `bind_turn_model`，避免 ops stub Turn 在 resume 后误走 live（例如无效 API key → 401）。

### 3.2 工作区与断言

- `prepare_ops_workspace` / `apply_fixtures`：目录 `0777`、fixture 文件 `0666`，并对 `.agent/...` 等祖先目录 chmod，避免 root 建树后 runtime 无法写 draft/export。
- 事件等待默认超时 **180s**（须大于 runtime `MODEL_TIMEOUT_SECONDS`，否则如 `shared.07` 会在 timeout 事件前被 ops 侧超时）。
- `sse.reconnect`：若首段 poll 已含终态事件，不再二次 wait（避免 stub 极快完成时挂死）。

### 3.3 API

前缀：`/api/v1/ops/eval`（需 `OPS_TEST_SECRET`）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/meta` | `restart_available` 等 |
| GET | `/cases` | 用例元数据 |
| POST | `/runs` | 创建 run：`{ mode, case_ids?, model?, restart_runtime? }` |
| GET | `/runs/{id}` | 状态与每条结果（含 `summary.pass|fail|skipped`） |
| GET | `/runs/{id}/stream` | SSE 进度（旁路，非写作 SSE） |

执行器在 api 进程内 asyncio 任务跑；断言逻辑自 `scripts/eval_run.py` 抽到 `services/api/app/services/ops/`。

## 4. 与 `make gate` / CI

| 场景 | 路径 |
|------|------|
| 日常自测、改完看红绿 | **本评测台** |
| CI / 无头 / 需隔离栈 / 环境耦合用例 | `make gate`、`make eval-*`（见 [28](28-proof-gate-and-ux-signals.md)） |

评测不挂写作工作台导航，避免误触。

## 5. 配置

```bash
# .env
OPS_TEST_SECRET=your-long-random-secret
```

Compose 已为 api 挂载 workspace、`eval/golden`、Docker socket；api 镜像需含 `docker` CLI（`docker-cli` + `docker-compose`；Debian Trixie 下仅装 `docker.io` 可能没有 `docker` 二进制）。「跑前重建 runtime」优先 compose force-recreate，失败则 `docker restart`。

改完 api/runtime 后请 `make up-api` / `make up-runtime` 重建镜像；仅热拷贝源码时注意包可能从 `site-packages` 加载，与 `/app/app` 不一致。
