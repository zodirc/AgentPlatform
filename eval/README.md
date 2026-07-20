# eval/

Golden Turn 与回归用例。规范见 **[`docs/11-eval-and-golden-turns.md`](../docs/11-eval-and-golden-turns.md)**。

Schema：`packages/contracts/eval/golden_turn.schema.json`

## 用例分布（当前）

| 目录 | 数量 | 说明 |
|------|------|------|
| `golden/shared/` | 15 | 管道、取消、幂等、HA、stall、outbox worker |
| `golden/agent/` | 9 | agent 场景（含 approval / deny / delegate） |
| `golden/writing/` | 14 | writing 场景（含 `writing.14` path_prefix） |
| `golden/interview/` | 1 | interview stub |
| `golden/live/` | 2 | 需 `MODEL_API_KEY`（nightly CI） |
| `retrieval/` | — | 离线 A/B 题集 + corpus（[docs/15](../docs/15-rag-and-sources.md)） |

**默认 stub 集：随 writing.14 增加**（排除 live / recorded / stall / ha / queue 标签）

## 运行

```bash
make smoke              # L0
make eval-all           # stub golden
make eval-retrieval     # retrieval profile（writing.07）
make retrieval-bench    # 离线检索 A/B（效果闸层 1）
make turn-effect-bench  # 层 1 + writing.14/12/13（本地栈需 MODEL_MODE=stub）
make eval-path-prefix   # isolated writing.14 golden
make eval-queue         # queue + worker（shared.16）
make eval-live          # live golden（需 MODEL_API_KEY）
python3 scripts/eval_run.py --phase 2
```

效果闸手工清单：[`retrieval/EFFECT_CHECKLIST.md`](retrieval/EFFECT_CHECKLIST.md)。

## CI 分层

| 层级 | 触发 | 内容 |
|------|------|------|
| L0–L3 | PR `ci.yml` | smoke、phase eval、retrieval、queue、HA、stall |
| L2 live | `nightly.yml` cron | `make eval-live` |
| L3 load | `nightly.yml` | `load_test.py` |
