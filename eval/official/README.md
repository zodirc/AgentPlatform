# Official small benches（挂载拉取 + Ops 可视化）

官方小量：`BEIR` · `LongBench` · `SWE-bench Lite`。  
数据进 `BENCH_DATA_DIR`（默认 `~/.cache/agentplatform-bench`），**不进 git**。  
协议：`protocol_version: official-small-2026-08-m1`（见 [`suites.small.yaml`](suites.small.yaml)）。

每次跑分写：

- 过程：`eval/reports/official/runs/<uuid>/process.jsonl`（**不进 git**）
- 结果：`manifest.json` / `result.json`
- 可视化：`report.html`（浏览器直接打开）
- Ops：自动 `publish`（需 `OPS_TEST_SECRET` + 栈）→ **官方评测**页 / 历史 `suite=official`
- **仓库一眼看板**：[`baseline/SCORECARD.md`](baseline/SCORECARD.md)（主指标表）  
- **机器锚点**：`baseline/<protocol_version>.json`  
  Live 调优：`make official-bench-live` → `make official-bench-compare` → 认可后 `make official-bench-update-baseline`

---

## 全过程（你该始终看懂的三步）

每个套件都是同一心智模型，日志里会打 `[phase]` / `[pull]` / `[eval]` / `[regress]`：

1. **拉取 Pull** — 官方题集进 `BENCH_DATA_DIR`；**已有则跳过**（日志 `cached`）。
2. **评测 Eval** — 出官方指标（nDCG、retention、patch 率 / harness resolve 等）。
3. **回归 Regress** — 检索会自动对比上次 `latest_retrieval.json`；其它套件在 Ops「多次结果对比」看 Δ。

**同条件才可比 Δ**：相同 `protocol_version`；编码还要相同 `coding_tier` + `n_instances` + 选题指纹。

**效果聚合排除**：上下文 dry、编码 skip（空补丁）、reclaimed、仅 hash 冒烟检索 — 不作效果结论。

**要不要挂加速器？** 只在「第一次拉取」可能需要：BEIR 走德国 UKP，LongBench/SWE 走 Hugging Face。国内若卡住就开代理或 HF 镜像；**拉完会缓存，之后主要是 ②③，不必常开代理**。

> Ops 容器内数据目录固定为 `/data/ops-official/data`（挂载到主机 `eval/official/.local-data`）。若曾把主机绝对路径写进 `BENCH_DATA_DIR`，容器内会找不到缓存而反复下载——现已强制容器内路径。

---

## Ops 一键（推荐）

打开 `http://localhost/ops/<OPS_TEST_SECRET>/official`：

- 顶部三步说明 + **当前阶段**条 + 全过程日志
- **评判标准**卡片：每套官方来源、指标、如何判定
- 勾选目标 → **开始官方评测** → **进度条 + 流式日志**
- ① 检索：**默认 ST 真向量**（独立 `agent-bench` + **专用 `bench-postgres`/pgvector**，不碰产品库）；仅调试管线时再改用 hash 冒烟或 `BENCH_RETRIEVAL_BACKEND=json`
- ② 上下文：三臂 **full / truncate / ContextEngine compact**（bench 内 import，不写产品 sessions）；「无模型（管道）」= dry
- ③ 编码：可调档 **3 / 5 / 10 / 25（默认）/ full300 / custom≥3**；默认 bench 直出 patch；官方 resolve 需勾选 harness（Docker）
- 评测模型区 **测试联通**：从 `agent-bench` 出站短请求（与正式评测同路径）；DeepSeek 预设默认 `deepseek-v4-flash`
- 聊天调用自动重试瞬断 / 429 / 5xx（`BENCH_MODEL_MAX_RETRIES`，默认 6）
- 历史旁 **清空**：删 Bench 历史与报告目录，**保留** BEIR 等数据缓存

重建：`make up-bench && make up-api && make up-web`（`up-bench` 会拉起 `bench-postgres`）

**架构**：评测跑在独立 **`agent-bench`**；Ops/api 只编排；**不进 agent runtime / Turn**（除非显式 `BENCH_CODING_VIA_PLATFORM=1`）。

- 默认「仅检索」= ST MiniLM 效果分
- 「仅检索·hash 冒烟」= 可选、只验管线

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
# live 三臂（需密钥）：
# export BENCH_MODEL_API_KEY=...
# make official-bench-context

# ③ 编码 SWE-bench Lite（默认档 n25）
make official-bench-coding-pull
make official-bench-coding-infer OFFICIAL_SWE_SKIP_API=1 OFFICIAL_SWE_TIER=n25
# 真推理（bench 模型密钥）：去掉 OFFICIAL_SWE_SKIP_API
# 官方 Docker 评分：
# pip install swebench && make official-bench-coding-eval
# 或 infer 时 OFFICIAL_SWE_HARNESS=1
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

| Make 目标 | 官方来源 | 指标 | 产品对齐 | 非对齐 |
|-----------|----------|------|----------|--------|
| `official-bench-retrieval` | BEIR | nDCG@k / Recall@k | 平台 hybrid + ST/pgvector（bench 专用库）；hybrid 搜索默认 thread（避免 ST×N OOM），BM25 默认 process | hash 冒烟 |
| `official-bench-context` | LongBench | full / truncate / compact F1 + retention | ContextEngine assemble（库导入）；pull 走官方 `data.zip`（兼容 datasets≥4） | dry 管道 |
| `official-bench-coding-*` | SWE-bench Lite | patch_rate；**resolve=harness** | bench 直出 patch + 固定档位切片 | skip_api；产品 Turn（默认关） |

改 harness 后：固定模型与 `protocol_version`（及编码档指纹），对比两次 `report.html` / Ops 指标 Δ。
