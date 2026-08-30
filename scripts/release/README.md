# 部署看板（:9090）

产品文档见 [导览 · 部署拓扑](../../docs/tour/index.html#topology)。本文件是脚本侧速查。

两种场景：

| 模式 | 用途 | 检测 |
|------|------|------|
| **本地开发** | 本机改代码，先试再 commit | 已提交 + **未提交** |
| **同步部署** | 换机器 / 对齐远程后再发 | **仅已提交**；先点「拉取远程」 |

左：检查项 + 一键重建/同步。右：详情 + 分模块日志（含 `git`）。

```bash
make up                 # 分模块起栈并拉起看板
make release-plan       # 终端看同一份健康 JSON
http://127.0.0.1:9090/
# 看板改 server.py 后需重启进程；工具栏「重启看板」或：
bash scripts/release/stop_console.sh && bash scripts/release/ensure_console.sh
```

| 模块 | 路径（`paths.env`） | 命令 |
|------|---------------------|------|
| api | `services/api/` · contracts · ddl · official_bench | `make up-api` |
| runtime | 编排核（controller/engine/tools/writing…） | `make up-runtime` |
| sources_retrieval | `retrieval/` · `platform_bus/` · `planes.yml` · embedding profile | `make up-sources-retrieval` |
| model_gateway | `gateway_service.py` · `services/model-gateway/` · `runtime:slim` | `make up-model-gateway` |
| sandbox | `sandbox_plane/` · `services/sandbox/` · `runtime:slim` | `make up-sandbox` |
| ast_indexer | workspace AST worker | `make up-ast-indexer` |
| web | `services/web/` | `make up-web` |
| gateway | caddy / compose | recreate |
| **Ops · SWE 评测环境** | docker.sock（api+runtime）+ `sweb.eval` + 冒烟 | `make ops-swe-eval-ready` |

官方 coding **必要一步**：挂 sock、预拉镜像、环境冒烟合成一键。约 1GiB/题，**不进 git**。Eval 默认 `cache_level=instance`。取消 sock：`make ops-eval-off`。

左侧目录树按轨划分：

```
产品 Agent/
  代码/          api · runtime · sources-retrieval · model-gateway · sandbox · ast-indexer · web · gateway
  中间件/        redis（job bus；上游镜像，`make start-redis`）
  检索/          向量模型（sources-retrieval）· 语料索引
Ops/
  检索/          向量模型（共用 sources-retrieval）· BEIR · C-MTEB
  评测/          Ops Bench · SWE 评测环境
```

Ops 嵌入复用 `agent-sources-retrieval` 的同一 `EMBEDDING_MODEL`（C-MTEB 另要求 bge-m3），与产品语料索引分库（`agent-postgres` vs `agent-bench-postgres`）。换模请重建 **sources-retrieval**，不是编排 runtime。

确认：看板模块变绿 · `deployed_sha` / `worktree_digest` 已 mark · `docker compose ps` healthy · `curl -fsS http://localhost/health/live`。

状态与日志：`reports/release/status.json` · `reports/release/logs/`。
