# Offline retrieval bench (docs/27 §8.1 · docs/28 RE0/RE3 · docs/30 IX4)

Layer-1 A/B harness for `search_sources` quality — **no agent loop**.

## Layout

```text
eval/retrieval/
├── README.md
├── EFFECT_CHECKLIST.md
├── HARD_WORKBENCH.md   # IX4 难自然问句（工作台复制；禁止 slash）
├── corpus/             # fixed sources tree → copied to tmp/sources/
│   ├── hr/
│   ├── legal/
│   └── writing/
├── qrels.yaml          # 近似闸（hash-bench）；filter / 题集回归
├── qrels_hard.yaml     # IX4 难 qrels（prod-bench 默认）
└── (runner: scripts/retrieval_bench.py)
```

## Two tracks

| 命令 | 后端 | 题集 | 证明什么 |
|------|------|------|----------|
| `make retrieval-bench` | json + **hash** | `qrels.yaml` | 契约/filter 逻辑；**≠** 生产召回 |
| `make retrieval-bench-prod` | 容器内 **ST + pgvector**（schema `retrieval_bench`） | `qrels_hard.yaml` | **真相档**难检索 / 噪声 |

Prod 使用独立 Postgres schema，避免 sync 隔离临时语料时删掉用户 `public` 索引。

人工体感：见 [`HARD_WORKBENCH.md`](HARD_WORKBENCH.md)（自然语言，禁止 slash）。

## Hit field baseline (RE0)

| Field | Hybrid / vector hit | Keyword (filesystem) before RE1 | Notes |
|-------|---------------------|----------------------------------|-------|
| `path` | yes | yes | workspace-relative |
| `chunk_id` | yes | no (file-level) | RE1 may add when section-parsed |
| `citation_id` | yes (`cite:{stem}`) | yes | required for cite loop |
| `excerpt` | yes | yes | truncated |
| `score` | yes | often absent | keyword may omit |
| `section_title` | yes | no (until RE1) | intentional gap |
| `line_start` / `line_end` | yes | no (until RE1) | intentional gap |

`path_prefix` (RE0 freeze): optional string; relative; auto-prefixed with `sources/` if omitted; reject `..` / absolute; illegal → empty hits + `hint`.

## Run

```bash
# 近似（本机 / CI 快）
make retrieval-bench

# 真相档难闸（需 agent-runtime healthy + ST 镜像）
make retrieval-bench-prod
```

报告含 pass 数、avg Recall@1 / @k、噪声计数。合并检索质量 PR：**prod 绿**（或书面豁免）+ 难工作台记录。

## Effect gate

- RE3：hash-bench 上 path_prefix A/B 仍可用。  
- **IX4**：`retrieval-bench-prod` 难 qrels 必过；浅常识题不算充分。
