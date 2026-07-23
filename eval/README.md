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

**Web 评测台（[docs/29](../docs/29-ops-eval-console.md)）**：日常红绿主路径。含 `ws.stream` / `wait-index` / `session-turns` / `admin.create-provider` 的用例会 **skipped**（≠ fail）；全量仍用下面 `make gate` / `make eval-*`。

## 运行

```bash
# 日常：浏览器打开 /ops/<OPS_TEST_SECRET>/test（docs/29）
make gate               # Proof 一键（smoke → eval-all → runtime-test；docs/28）
make smoke              # L0（单独）
make eval-all           # stub golden
make ux-signals         # 体验信号自检（docs/28 PX1；环外）
make eval-retrieval     # retrieval profile（writing.07）
make retrieval-bench    # 离线检索 A/B（效果闸层 1）
make turn-effect-bench  # 层 1 + writing.14/12/13（本地栈需 MODEL_MODE=stub）
make eval-path-prefix   # isolated writing.14 golden
make eval-queue         # queue + worker（shared.16）
make eval-live          # live golden（需 MODEL_API_KEY）
python3 scripts/eval_run.py --phase 2
```

效果闸手工清单：[`retrieval/EFFECT_CHECKLIST.md`](retrieval/EFFECT_CHECKLIST.md)。

体验信号：[`ux_signals/README.md`](ux_signals/README.md)。

## CI 分层

| 层级 | 触发 | 内容 |
|------|------|------|
| L0 + L1 | PR / push `.github/workflows/ci.yml` | `make smoke`、`make eval-all`、runtime/contracts/ux-signals 单测（**阻断**） |
| L1c 加跑 | 改 retrieval/queue 时本地 | `make eval-retrieval` / `make eval-queue`（见 ci.yml 注释） |
| L2 live | `.github/workflows/nightly.yml` | `make eval-live`（**告警不阻断**） |
