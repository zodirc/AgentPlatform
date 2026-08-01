# Official small benches（挂载拉取 + Ops 可视化）

官方小量：`BEIR` · `LongBench` · `SWE-bench Lite`。  
数据进 `BENCH_DATA_DIR`（默认 `~/.cache/agentplatform-bench`），**不进 git**。  
每次跑分写：

- 过程：`eval/reports/official/runs/<uuid>/process.jsonl`
- 结果：`manifest.json` / `result.json`
- 可视化：`report.html`（浏览器直接打开）
- Ops：自动 `publish`（需 `OPS_TEST_SECRET` + 栈）→ **官方评测**页 / 历史 `suite=official`

协议钉死：[`suites.small.yaml`](suites.small.yaml)。

---

## 全过程（你该始终看懂的三步）

每个套件都是同一心智模型，日志里会打 `[phase]` / `[pull]` / `[eval]` / `[regress]`：

1. **拉取 Pull** — 官方题集进 `BENCH_DATA_DIR`；**已有则跳过**（日志 `cached`）。
2. **评测 Eval** — 出官方指标（nDCG、retention、patch 率等）。
3. **回归 Regress** — 检索会自动对比上次 `latest_retrieval.json`；其它套件在 Ops「多次结果对比」看 Δ。

**要不要挂加速器？** 只在「第一次拉取」可能需要：BEIR 走德国 UKP，LongBench/SWE 走 Hugging Face。国内若卡住就开代理或 HF 镜像；**拉完会缓存，之后主要是 ②③，不必常开代理**。

> Ops 容器内数据目录固定为 `/data/ops-official/data`（挂载到主机 `eval/official/.local-data`）。若曾把主机绝对路径写进 `BENCH_DATA_DIR`，容器内会找不到缓存而反复下载——现已强制容器内路径。

---

## Ops 一键（推荐）

打开 `http://localhost/ops/<OPS_TEST_SECRET>/official`：

- 顶部三步说明 + **当前阶段**条 + 全过程日志
- **评判标准**卡片：每套官方来源、指标、如何判定
- 勾选目标 → **开始官方评测** → **进度条 + 流式日志**
- ① 检索（BEIR）默认 **平台 hybrid + BM25 对照**；②③ 需 api 安装 `datasets`（镜像已 bake）或改用下方主机 make
- 历史旁 **清空**：删官方评测 DB 记录与报告目录，**保留** BEIR 等数据缓存

重建以加载新 API/Web：`make up-api && make up-web`

---

## 主机命令（复制即用）

前置：仓库根目录；建议栈已 `make up`；`.env` 里已有 `OPS_TEST_SECRET`。

```bash
cd /home/ropz/AgentPlatform

# 0) 环境（publish 进 Ops）
set -a && source .env && set +a
export BENCH_PUBLISH=1
# 可选：export BENCH_DATA_DIR=$HOME/.cache/agentplatform-bench

# 依赖（LongBench / SWE 拉取需要；纯 BEIR 只需 PyYAML）
python3 -m pip install -r eval/official/requirements.txt
```

### 独立跑（推荐）

```bash
# 拉数据（三套都拉；可重复，有缓存）
make official-bench-pull

# ① 检索 BEIR 小量（SciFact + NFCorpus + FiQA）— 通常可离线算完
make official-bench-retrieval

# ② 上下文 LongBench 小量
make official-bench-context CONTEXT_DRY=1          # 只验证流水线/过程落盘（无模型）
# live 双臂（需密钥）：
# export BENCH_MODEL_API_KEY=...
# make official-bench-context

# ③ 编码 SWE-bench Lite
make official-bench-coding-pull
make official-bench-coding-infer OFFICIAL_SWE_SKIP_API=1   # 先打通 predictions 落盘
# 真推理（需平台可登录/API）：去掉 OFFICIAL_SWE_SKIP_API
# 官方 Docker 评分（盘大、时长长）：
# pip install swebench && make official-bench-coding-eval
```

### 一次性（检索必跑；上下文/编码可选）

```bash
make official-bench-all
# 或：
# WITH_CONTEXT=1 CONTEXT_DRY=1 make official-bench-all
# WITH_CODING_INFER=1 OFFICIAL_SWE_SKIP_API=1 请改用分开的 coding-infer 目标
```

### 若自动 publish 失败，手动导入最新一次

```bash
set -a && source .env && set +a
make official-bench-publish
# 或：RUN_ID=<uuid> make official-bench-publish
```

---

## 怎么看过程 / 结果

| 方式 | 路径 |
|------|------|
| **本地 HTML** | `eval/reports/official/runs/<uuid>/report.html`（指标条 + 用例表 + 过程日志） |
| **最新指针** | `eval/reports/official/latest_run.json` · `latest_retrieval.json` 等 |
| **Ops 官方评测页** | `http://localhost/ops/<OPS_TEST_SECRET>/official` |
| **Ops 历史** | `…/test/history` → 套件筛 `official` |
| **Ops Run 详页** | 官方页里点「Ops Run 详页」或 `…/test/runs/<uuid>` |

取密钥：

```bash
grep OPS_TEST_SECRET .env
```

---

## 套件说明（可信边界）

| Make 目标 | 官方来源 | 指标 | 说明 |
|-----------|----------|------|------|
| `official-bench-retrieval` | BEIR | nDCG@k / Recall@k | **主分=平台 hybrid**；BM25 为对照地板 |
| `official-bench-context` | LongBench | full vs budget F1 + retention | live 需模型；`CONTEXT_DRY=1` 只验证落盘 |
| `official-bench-coding-*` | SWE-bench Lite | pull / patch 率 / harness | **官方分**仅 `coding-eval` + Docker |

改 harness 后：固定模型与 `protocol_version`，对比两次 `report.html` / Ops 指标 Δ。
