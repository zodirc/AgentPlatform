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
```

| 模块 | 路径（`paths.env`） | 命令 |
|------|---------------------|------|
| api | `services/api/` · `packages/contracts/` | `make up-api` |
| runtime | `services/runtime/` · `packages/contracts/` | `make up-runtime` |
| web | `services/web/` | `make up-web` |
| gateway | caddy / compose | recreate |

确认：看板模块变绿 · `deployed_sha` / `worktree_digest` 已 mark · `docker compose ps` healthy · `curl -fsS http://localhost/health/live`。

状态与日志：`reports/release/status.json` · `reports/release/logs/`。
