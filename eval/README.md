# eval/

Golden Turn 与回归用例。规范见 **[`docs/12-eval-and-golden-turns.md`](../docs/12-eval-and-golden-turns.md)**。

Schema：`packages/contracts/eval/golden_turn.schema.json`

## 用例分布（当前）

| 目录 | 数量 | 说明 |
|------|------|------|
| `golden/shared/` | 15 | 管道、取消、幂等、HA、stall、outbox worker |
| `golden/agent/` | 9 | agent 场景（含 approval / deny / delegate） |
| `golden/writing/` | 9 | writing 场景 |
| `golden/interview/` | 1 | interview stub |
| `golden/live/` | 2 | 需 `MODEL_API_KEY`（nightly CI） |

**默认 stub 集：31 条**（排除 live / recorded / stall / ha / queue 标签）  
**YAML 合计：37 条**

## 运行

```bash
make smoke              # L0
make eval-all           # 31 条 stub golden
make eval-retrieval     # retrieval profile（writing.07）
make eval-queue         # queue + worker（shared.16）
make eval-live          # live golden（需 MODEL_API_KEY）
python3 scripts/eval_run.py --phase 2
```

## CI 分层

| 层级 | 触发 | 内容 |
|------|------|------|
| L0–L3 | PR `ci.yml` | smoke、phase eval、retrieval、queue、HA、stall |
| L2 live | `nightly.yml` cron | `make eval-live` |
| L3 load | `nightly.yml` | `load_test.py` |
