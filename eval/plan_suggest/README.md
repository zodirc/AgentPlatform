# Plan suggest eval (docs/26)

| 文件 | 用途 |
|------|------|
| [`../../packages/contracts/plan_suggest/weights.json`](../../packages/contracts/plan_suggest/weights.json) | **唯一线上权重配置**（改这一份） |
| `cases.json` | CI 快测子集 |
| `golden.jsonl` | 金标大盘 |
| `reports/` | eval / tune 输出（gitignore） |

## 两种用法

| 命令 | 干什么 | 会不会改线上 |
|------|--------|--------------|
| `make eval-plan-suggest` | 体检：用 `weights.json` 跑金标 | 否 |
| `make eval-plan-suggest-tune` | 参谋：搜更好权重，写 `proposed_config` | 否（只出草稿） |

## 想改线上灵敏度

1. 编辑 `packages/contracts/plan_suggest/weights.json`  
   （或把 tune 报告里的 `proposed_config` 整份覆盖进去）
2. `make eval-plan-suggest` 确认 P/R
3. 重建 **web + runtime**（两端都读这份文件）

```bash
make eval-plan-suggest
# 改 weights.json …
make up-web up-runtime   # 或你的日常发布命令
```
