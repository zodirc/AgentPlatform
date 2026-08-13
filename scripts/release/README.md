# 部署看板（:9090）

产品文档见 [docs/core/architecture.md](../../docs/core/architecture.md) §分模块发布。本文件是脚本侧速查。

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
| api | `services/api/` · `packages/contracts/` | `make up-api` |
| runtime | `services/runtime/` · `packages/contracts/` | `make up-runtime` |
| web | `services/web/` | `make up-web` |
| gateway | caddy / compose | recreate |
| **Ops · SWE eval 镜像** | `suites.coding.harness`（默认 n5） | `make official-bench-coding-pull-images`（看板一键） |

SWE 官方 resolve 依赖本机 `sweb.eval` 镜像（约 1GiB/题，**不进 git**）。启用 `make up-ops-eval` 后看板会检查是否已预拉；缺则点「预拉 SWE eval 镜像」。Eval 默认 `cache_level=instance`，避免跑完删掉镜像。

拉取时可实时观测：顶栏/该项 detail 显示 **网速（MiB/s）· 镜像 n/N · 综合% · 层 done/total · 已下字节/总字节 · 当前镜像**（读 `reports/release/swe_eval_images_progress.json`，由已下字节滑动窗口估速）；日志 tab「SWE 镜像」流式输出原文。排队 Waiting、尚无字节计数时不显示网速。

左侧目录树按轨划分：

```
产品 Agent/
  代码/          api · runtime · ast-indexer · web · gateway
  检索/          向量模型 · 语料索引
Ops/
  检索/          向量模型（共用 runtime）· BEIR 英文索引 · C-MTEB 中文索引
  评测/          SWE eval 镜像
```

Ops 嵌入复用 `agent-runtime` 的同一 `EMBEDDING_MODEL`（C-MTEB 另要求 bge-m3），与产品语料索引分库（`agent-postgres` vs `agent-bench-postgres`）。点文件夹展开/收起；偏好键 `localStorage.releaseTreeOpen`。

确认：看板模块变绿 · `deployed_sha` / `worktree_digest` 已 mark · `docker compose ps` healthy · `curl -fsS http://localhost/health/live`。

状态与日志：`reports/release/status.json` · `reports/release/logs/`。
